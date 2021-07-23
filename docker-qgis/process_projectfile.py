import logging
import sys
from pathlib import Path
from typing import List
from xml.etree import ElementTree

from qfieldcloud.qgis.utils import (
    BaseException,
    get_layer_filename,
    has_ping,
    is_localhost,
    start_app,
)
from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsProject
from qgis.PyQt.QtCore import QEventLoop, QSize
from qgis.PyQt.QtGui import QColor

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


def check_layer_validity(project: QgsProject) -> List:
    logging.info("Check layer and datasource validity...")

    has_invalid_layers = False
    layers_summary = []

    for layer in project.mapLayers().values():
        error = layer.error()
        layer_data = {
            "id": layer.name(),
            "name": layer.name(),
            "is_valid": layer.isValid(),
            "datasource": layer.dataProvider().uri().uri(),
            "error_summary": error.summary() if error.messageList() else "",
            "error_message": layer.error().message(),
            "filename": get_layer_filename(layer),
            "provider_error_summary": None,
            "provider_error_message": None,
        }
        layers_summary.append(layer_data)

        if layer_data["is_valid"]:
            continue

        has_invalid_layers = True
        data_provider = layer.dataProvider()

        if data_provider:
            data_provider_error = data_provider.error()

            layer_data["provider_error_summary"] = (
                data_provider_error.summary()
                if data_provider_error.messageList()
                else ""
            )
            layer_data["provider_error_message"] = data_provider_error.message()

            if not layer_data["provider_error_summary"]:
                service = data_provider.uri().service()
                if service:
                    layer_data[
                        "provider_error_summary"
                    ] = f'Unable to connect to service "{service}"'

                host = data_provider.uri().host()
                port = (
                    int(data_provider.uri().port())
                    if data_provider.uri().port()
                    else None
                )
                if host and (is_localhost(host, port) or has_ping(host)):
                    layer_data[
                        "provider_error_summary"
                    ] = f'Unable to connect to host "{host}"'

        else:
            layer_data["provider_error_summary"] = "No data provider available"

    if has_invalid_layers:
        raise InvalidLayersException(layers_summary=layers_summary)

    return layers_summary


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
