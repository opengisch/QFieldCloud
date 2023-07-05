import logging
from pathlib import Path
from typing import Dict
from xml.etree import ElementTree

from qfieldcloud.qgis.utils import BaseException, get_layers_data, layers_data_to_string
from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsProject
from qgis.PyQt.QtCore import QEventLoop, QSize
from qgis.PyQt.QtGui import QColor

logger = logging.getLogger("PROCPRJ")


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
    logger.info("Check QGIS project file validity…")

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

    logger.info("QGIS project file is valid!")


def load_project_file(project_filename: Path) -> QgsProject:
    logger.info("Open QGIS project file…")

    project = QgsProject.instance()
    if not project.read(str(project_filename)):
        raise InvalidXmlFileException(error=project.error())

    logger.info("QGIS project file opened!")

    return project


def extract_project_details(project: QgsProject) -> Dict[str, str]:
    """Extract project details"""
    logger.info("Extract project details…")

    details = {}

    logger.info("Reading QGIS project file…")
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

    logger.info("Extracting layer and datasource details…")

    details["layers_by_id"] = get_layers_data(project)
    details["ordered_layer_ids"] = list(details["layers_by_id"].keys())
    details["attachment_dirs"], _ = project.readListEntry(
        "QFieldSync", "attachmentDirs", ["DCIM"]
    )

    logger.info(
        f'QGIS project layer checks\n{layers_data_to_string(details["layers_by_id"])}',
    )

    return details


def generate_thumbnail(project: QgsProject, thumbnail_filename: Path) -> None:
    """Create a thumbnail for the project

    As from https://docs.qgis.org/3.16/en/docs/pyqgis_developer_cookbook/composer.html#simple-rendering

    Args:
        project (QgsProject)
        thumbnail_filename (Path)
    """
    logger.info("Generate project thumbnail image…")

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

    logger.info("Project thumbnail image generated!")


if __name__ == "__main__":
    from qfieldcloud.qgis.utils import setup_basic_logging_config

    setup_basic_logging_config()
