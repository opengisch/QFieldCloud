import logging
from pathlib import Path
from typing import Any, TypedDict, cast
from xml.etree import ElementTree

from qgis.core import (
    QgsMapRendererCustomPainterJob,
    QgsProject,
)
from qgis.PyQt.QtGui import QImage, QPainter

from .utils import (
    FailedThumbnailGenerationException,
    InvalidFileExtensionException,
    InvalidXmlFileException,
    ProjectFileNotFoundException,
    get_layers_data,
    get_qgis_xml_error_context,
    layers_data_to_string,
    open_qgis_project_temporarily,
)

logger = logging.getLogger("PROCPRJ")


def check_valid_project_file(the_qgis_file_name: Path) -> None:
    logger.info("Check QGIS project file validity…")

    if not the_qgis_file_name.exists():
        raise ProjectFileNotFoundException(the_qgis_file_name=the_qgis_file_name)

    if the_qgis_file_name.suffix == ".qgs":
        with open(the_qgis_file_name, "rb") as fh:
            try:
                for event, elem in ElementTree.iterparse(fh):
                    continue
            except ElementTree.ParseError as error:
                error_msg = str(error)
                raise InvalidXmlFileException(
                    xml_error=get_qgis_xml_error_context(error_msg, fh) or error_msg,
                    the_qgis_file_name=the_qgis_file_name,
                )
    elif the_qgis_file_name.suffix != ".qgz":
        raise InvalidFileExtensionException(
            the_qgis_file_name=the_qgis_file_name,
            extension=the_qgis_file_name.suffix,
        )

    logger.info("QGIS project file is valid!")


class ProjectDetails(TypedDict):
    background_color: str
    extent: str
    crs: str
    project_name: str
    layers_by_id: dict[str, Any]
    ordered_layer_ids: list[str]
    attachment_dirs: list[str]
    data_dirs: list[str]


def extract_project_details(project: QgsProject) -> ProjectDetails:
    """Extract project details"""
    logger.info("Extract project details…")
    logger.info("Reading QGIS project file…")

    details: ProjectDetails = cast(ProjectDetails, {})
    tmp_project_details = open_qgis_project_temporarily(project.fileName())
    tmp_project = tmp_project_details["project"]

    # NOTE force delete the `QgsProject`, otherwise the `QgsApplication` might be deleted by the time the project is garbage collected
    del tmp_project

    details["background_color"] = tmp_project_details["background_color"]
    details["extent"] = tmp_project_details["extent"]
    details["crs"] = project.crs().authid()
    details["project_name"] = project.title()

    logger.info("Extracting layer and datasource details…")

    details["layers_by_id"] = get_layers_data(project)
    details["ordered_layer_ids"] = list(details["layers_by_id"].keys())
    details["attachment_dirs"], _ = project.readListEntry(
        "QFieldSync", "attachmentDirs", ["DCIM"]
    )
    details["data_dirs"], _ = project.readListEntry("QFieldSync", "dataDirs", [])

    logger.info(
        f"QGIS project layer checks\n{layers_data_to_string(details['layers_by_id'])}",
    )

    return details


def generate_thumbnail(the_qgis_file_name: str, thumbnail_filename: Path) -> None:
    """Create a thumbnail for the project

    As from https://docs.qgis.org/3.16/en/docs/pyqgis_developer_cookbook/composer.html#simple-rendering

    Args:
        the_qgis_file_name:
        thumbnail_filename:
    """
    logger.info("Generate project thumbnail image…")

    tmp_project_details = open_qgis_project_temporarily(the_qgis_file_name)
    tmp_project = tmp_project_details["project"]
    map_settings = tmp_project_details["map_settings"]

    img = QImage(map_settings.outputSize(), QImage.Format_ARGB32)
    painter = QPainter(img)
    job = QgsMapRendererCustomPainterJob(map_settings, painter)
    # NOTE we use `renderSynchronously` as it does not crash and produces the thumbnail.
    # `waitForFinishedWithEventLoop` hangs forever and `waitForFinished` produces blank thumbnail, so don't use them!
    job.renderSynchronously()

    if not img.save(str(thumbnail_filename)):
        raise FailedThumbnailGenerationException(reason="Failed to save.")

    painter.end()

    # NOTE force delete the `QgsMapRendererCustomPainterJob`, `QPainter` and `QImage` because we are paranoid with Cpp objects around
    del job
    del painter
    del img
    # NOTE force delete the `QgsProject`, otherwise the `QgsApplication` might be deleted by the time the project is garbage collected
    del tmp_project

    logger.info("Project thumbnail image generated!")


if __name__ == "__main__":
    from qfc_worker.utils import setup_basic_logging_config

    setup_basic_logging_config()
