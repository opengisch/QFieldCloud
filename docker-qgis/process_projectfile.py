import logging
import sys
from pathlib import Path
from typing import Dict
from xml.etree import ElementTree

from libqfieldsync.layer import LayerSource
from qfieldcloud.qgis.utils import BaseException, has_ping, is_localhost, start_app
from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsProject
from qgis.PyQt.QtCore import QEventLoop, QSize
from qgis.PyQt.QtGui import QColor
from tabulate import tabulate

logging.basicConfig(
    stream=sys.stderr, level=logging.DEBUG, format="%(asctime)s %(levelname)s %(msg)s"
)


class ProjectFileNotFoundException(BaseException):
    message = 'Project file "%(project_filename)s" does not exist'


class InvalidFileExtensionException(BaseException):
    message = (
        'Project file "%(project_filename)s" has unknown file extension "%(extension)s"'
    )


class InvalidXmlFileException(BaseException):
    message = "Project file is an invalid XML document:\n%(xml_error)s"


class InvalidQgisFileException(BaseException):
    message = 'Project file "%(project_filename)s" is invalid QGIS file:\n%(error)s'


class InvalidLayersException(BaseException):
    message = 'Project file "%(project_filename)s" contains invalid layers'


class FailedThumbnailGenerationException(BaseException):
    message = "Failed to generate project thumbnail:\n%(reason)s"


def check_valid_project_file(project_filename: Path) -> None:
    logging.info("Check QGIS project file validity...")

    if not project_filename.exists():
        raise ProjectFileNotFoundException(project_filename=project_filename)

    if project_filename.suffix == ".qgs":
        try:
            with open(project_filename) as f:
                ElementTree.fromstring(f.read())
        except ElementTree.ParseError as err:
            raise InvalidXmlFileException(
                project_filename=project_filename, xml_error=err
            )
    elif project_filename.suffix != ".qgz":
        raise InvalidFileExtensionException(
            project_filename=project_filename, extension=project_filename.suffix
        )


def load_project_file(project_filename: Path) -> QgsProject:
    logging.info("Open QGIS project file...")

    start_app()

    project = QgsProject.instance()
    if not project.read(str(project_filename)):
        raise InvalidXmlFileException(error=project.error())

    return project


def extract_project_details(project: QgsProject) -> Dict[str, str]:
    """Extract project details"""
    logging.info("Extract project details...")

    details = {}

    logging.info("Reading QGIS project file...")
    map_settings = QgsMapSettings()

    def on_project_read(doc):
        r, _success = project.readNumEntry("Gui", "/CanvasColorRedPart", 255)
        g, _success = project.readNumEntry("Gui", "/CanvasColorGreenPart", 255)
        b, _success = project.readNumEntry("Gui", "/CanvasColorBluePart", 255)
        background_color = QColor(r, g, b)
        map_settings.setBackgroundColor(background_color)

        details["background_color"] = background_color.name()

        nodes = doc.elementsByTagName("mapcanvas")

        for i in range(nodes.size()):
            node = nodes.item(i)
            element = node.toElement()
            if (
                element.hasAttribute("name")
                and element.attribute("name") == "theMapCanvas"
            ):
                map_settings.readXml(node)

        map_settings.setRotation(0)
        map_settings.setOutputSize(QSize(1024, 768))

        details["extent"] = map_settings.extent().asWktPolygon()

    project.readProject.connect(on_project_read)
    project.read(project.fileName())

    details["crs"] = project.crs().authid()
    details["project_name"] = project.title()

    logging.info("Extracting layer and datasource details...")

    ordered_layer_ids = []
    layers_by_id = {}

    for layer in project.mapLayers().values():
        error = layer.error()
        layer_id = layer.id()
        layer_source = LayerSource(layer)
        ordered_layer_ids.append(layer_id)
        layers_by_id[layer_id] = {
            "id": layer_id,
            "name": layer.name(),
            "crs": layer.crs().authid() if layer.crs() else None,
            "is_valid": layer.isValid(),
            "datasource": layer.dataProvider().uri().uri()
            if layer.dataProvider()
            else None,
            "type": layer.type(),
            "type_name": layer.type().name,
            "error_code": "no_error",
            "error_summary": error.summary() if error.messageList() else "",
            "error_message": layer.error().message(),
            "filename": layer_source.filename,
            "provider_error_summary": None,
            "provider_error_message": None,
        }

        if layers_by_id[layer_id]["is_valid"]:
            continue

        data_provider = layer.dataProvider()

        if data_provider:
            data_provider_error = data_provider.error()

            if data_provider.isValid():
                # there might be another reason why the layer is not valid, other than the data provider
                layers_by_id[layer_id]["error_code"] = "invalid_layer"
            else:
                layers_by_id[layer_id]["error_code"] = "invalid_dataprovider"

            layers_by_id[layer_id]["provider_error_summary"] = (
                data_provider_error.summary()
                if data_provider_error.messageList()
                else ""
            )
            layers_by_id[layer_id][
                "provider_error_message"
            ] = data_provider_error.message()

            if not layers_by_id[layer_id]["provider_error_summary"]:
                service = data_provider.uri().service()
                if service:
                    layers_by_id[layer_id][
                        "provider_error_summary"
                    ] = f'Unable to connect to service "{service}"'

                host = data_provider.uri().host()
                port = (
                    int(data_provider.uri().port())
                    if data_provider.uri().port()
                    else None
                )
                if host and (is_localhost(host, port) or has_ping(host)):
                    layers_by_id[layer_id][
                        "provider_error_summary"
                    ] = f'Unable to connect to host "{host}"'

            logging.info(
                f'Layer "{layer.name()}" seems to be invalid: {layers_by_id[layer_id]["provider_error_summary"]}'
            )
        else:
            layers_by_id[layer_id]["error_code"] = "missing_dataprovider"
            layers_by_id[layer_id][
                "provider_error_summary"
            ] = "No data provider available"

    # Print layer check results
    table = [
        [
            d["name"],
            f'...{d["id"][-6:]}',
            d["is_valid"],
            d["error_code"],
            d["error_summary"],
            d["provider_error_summary"],
        ]
        for d in layers_by_id.values()
    ]
    logging.info(
        "\n".join(
            [
                "QGIS project layer checks",
                tabulate(
                    table,
                    headers=[
                        "Layer Name",
                        "Layer Id",
                        "Is Valid",
                        "Status",
                        "Error Summary",
                        "Provider Summary",
                    ],
                ),
            ]
        )
    )

    details["layers_by_id"] = layers_by_id
    details["ordered_layer_ids"] = ordered_layer_ids

    return details


def generate_thumbnail(project: QgsProject, thumbnail_filename: Path) -> None:
    """Create a thumbnail for the project

    As from https://docs.qgis.org/3.16/en/docs/pyqgis_developer_cookbook/composer.html#simple-rendering

    Args:
        project (QgsProject)
        thumbnail_filename (Path)
    """
    logging.info("Generate project thumbnail image...")

    map_settings = QgsMapSettings()
    layer_tree = project.layerTreeRoot()

    def on_project_read(doc):
        r, _success = project.readNumEntry("Gui", "/CanvasColorRedPart", 255)
        g, _success = project.readNumEntry("Gui", "/CanvasColorGreenPart", 255)
        b, _success = project.readNumEntry("Gui", "/CanvasColorBluePart", 255)
        map_settings.setBackgroundColor(QColor(r, g, b))

        nodes = doc.elementsByTagName("mapcanvas")

        for i in range(nodes.size()):
            node = nodes.item(i)
            element = node.toElement()
            if (
                element.hasAttribute("name")
                and element.attribute("name") == "theMapCanvas"
            ):
                map_settings.readXml(node)

        map_settings.setRotation(0)
        map_settings.setTransformContext(project.transformContext())
        map_settings.setPathResolver(project.pathResolver())
        map_settings.setOutputSize(QSize(100, 100))
        map_settings.setLayers(reversed(list(layer_tree.customLayerOrder())))
        # print(f'output size: {map_settings.outputSize().width()} {map_settings.outputSize().height()}')
        # print(f'layers: {[layer.name() for layer in map_settings.layers()]}')

    project.readProject.connect(on_project_read)
    project.read(project.fileName())

    renderer = QgsMapRendererParallelJob(map_settings)

    event_loop = QEventLoop()
    renderer.finished.connect(event_loop.quit)
    renderer.start()

    event_loop.exec_()

    img = renderer.renderedImage()

    if not img.save(str(thumbnail_filename)):
        raise FailedThumbnailGenerationException(reason="Failed to save.")
