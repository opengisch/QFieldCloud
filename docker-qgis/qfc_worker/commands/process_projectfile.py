import argparse
import logging
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import UUID
from xml.etree import ElementTree

from qgis.core import QgsMapRendererCustomPainterJob, QgsProject
from qgis.PyQt.QtGui import QImage, QPainter

from qfc_worker.commands_base import QfcBaseCommand
from qfc_worker.exceptions import (
    FailedThumbnailGenerationException,
    InvalidFileExtensionException,
    InvalidXmlFileException,
    ProjectFileNotFoundException,
)
from qfc_worker.utils import (
    download_project,
    get_layers_data,
    get_qgis_xml_error_context,
    layers_data_to_string,
    open_qgis_project_as_readonly,
    open_qgis_project_temporarily,
    start_app,
    stop_app,
)
from qfc_worker.workflow import (
    Step,
    StepOutput,
    WorkDirPath,
    WorkDirPathAsStr,
    Workflow,
    run_workflow,
)

logger = logging.getLogger(__name__)


def _check_valid_project_file(the_qgis_file_name: Path) -> None:
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


def _extract_project_details(project: QgsProject) -> ProjectDetails:
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


def _generate_thumbnail(the_qgis_file_name: str, thumbnail_filename: Path) -> None:
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


class ProcessProjectfileCommand(QfcBaseCommand):
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("project_id", type=UUID, help="Project ID")
        parser.add_argument("project_file", type=str, help="QGIS project file path")

    def handle(  # type: ignore
        self,
        project_id: UUID,
        project_file: str,
    ) -> None:
        workflow = Workflow(
            id="process_projectfile",
            name="Process Projectfile",
            version="2.0",
            steps=[
                Step(
                    id="start_qgis_app",
                    name="Start QGIS Application",
                    method=start_app,
                    return_names=["qgis_version"],
                ),
                Step(
                    id="download_project_directory",
                    name="Download Project Directory",
                    arguments={
                        "project_id": project_id,
                        "destination": WorkDirPath(mkdir=True),
                        "skip_attachments": True,
                    },
                    method=download_project,
                    return_names=["tmp_project_dir"],
                ),
                Step(
                    id="project_validity_check",
                    name="Project Validity Check",
                    arguments={
                        "the_qgis_file_name": WorkDirPath("files", project_file),
                    },
                    method=_check_valid_project_file,
                ),
                Step(
                    id="opening_check",
                    name="Opening Check",
                    arguments={
                        "the_qgis_file_name": WorkDirPathAsStr("files", project_file),
                        "force_reload": True,
                        "disable_feature_count": True,
                    },
                    method=open_qgis_project_as_readonly,
                    return_names=["project"],
                ),
                Step(
                    id="project_details",
                    name="Project Details",
                    arguments={
                        "project": StepOutput("opening_check", "project"),
                    },
                    method=_extract_project_details,
                    return_names=["project_details"],
                    outputs=["project_details"],
                ),
                Step(
                    id="generate_thumbnail_image",
                    name="Generate Thumbnail Image",
                    arguments={
                        "the_qgis_file_name": WorkDirPathAsStr("files", project_file),
                        "thumbnail_filename": Path("/io/thumbnail.png"),
                    },
                    method=_generate_thumbnail,
                ),
                Step(
                    id="stop_qgis_app",
                    name="Stop QGIS Application",
                    method=stop_app,
                ),
            ],
        )

        run_workflow(
            workflow,
            Path("/io/feedback.json"),
        )


cmd = ProcessProjectfileCommand()

if __name__ == "__main__":
    cmd.run_from_argv()
