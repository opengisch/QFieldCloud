import argparse
import logging
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import UUID
from xml.etree import ElementTree

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsMapRendererCustomPainterJob,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QImage, QPainter

from qfc_worker.commands_base import QfcBaseCommand
from qfc_worker.exceptions import (
    FailedThumbnailGenerationError,
    InvalidFileExtensionError,
    InvalidXmlFileError,
    ProjectFileNotFoundError,
)
from qfc_worker.utils import (
    download_project,
    get_layers_data,
    get_qgis_version_from_project_file,
    get_qgis_xml_error_context,
    layers_data_to_string,
    open_qgis_project_as_readonly,
    open_qgis_project_temporarily,
    reproject_extent,
    start_app,
    stop_app,
    upload_project_thumbnail,
)
from qfc_worker.workflow import (
    Step,
    StepOutput,
    WorkDirPath,
    WorkDirPathAsStr,
    Workflow,
)

THUMBNAIL_TIMEOUT_S = 10

logger = logging.getLogger(__name__)


def _check_valid_project_file(the_qgis_file_name: Path) -> None:
    logger.info("Check QGIS project file validity…")

    if not the_qgis_file_name.exists():
        raise ProjectFileNotFoundError(the_qgis_file_name=the_qgis_file_name)

    if the_qgis_file_name.suffix == ".qgs":
        with open(the_qgis_file_name, "rb") as fh:
            try:
                for event, elem in ElementTree.iterparse(fh):
                    continue
            except ElementTree.ParseError as error:
                error_msg = str(error)
                raise InvalidXmlFileError(
                    xml_error=get_qgis_xml_error_context(error_msg, fh) or error_msg,
                    the_qgis_file_name=the_qgis_file_name,
                )
    elif the_qgis_file_name.suffix != ".qgz":
        raise InvalidFileExtensionError(
            the_qgis_file_name=the_qgis_file_name,
            extension=the_qgis_file_name.suffix,
        )

    logger.info("QGIS project file is valid!")


class ProjectDetails(TypedDict):
    """
    The data structure built by `_extract_project_details` and returned as the `process_projectfile` job's `project_details` output.

    Must be kept in sync with `QgisProjectDetails` in `qfieldcloud/project/type_defs.py`, which consumes this data structure.

    WARNING: this shape has evolved over time, so feedback stored by older jobs is not guaranteed to match it.
    """

    background_color: str
    extent: str
    """The project extent, reprojected to WGS84 (EPSG:4326) WKT, or an empty string if the reprojection failed."""
    area_of_interest: str
    """The area of interest, reprojected to WGS84 (EPSG:4326) WKT, or an empty string if not set or if the reprojection failed."""
    crs: str
    project_name: str
    layers_by_id: dict[str, Any]
    ordered_layer_ids: list[str]
    attachment_dirs: list[str]
    data_dirs: list[str]
    qgis_version: str


def _get_area_of_interest(project: QgsProject) -> QgsRectangle | None:
    aoi_wkt, _ = project.readEntry("qfieldsync", "/areaOfInterest")
    aoi_crs, _ = project.readEntry("qfieldsync", "/areaOfInterestCrs")

    if not aoi_wkt or not aoi_crs:
        return None

    aoi_crs_obj = QgsCoordinateReferenceSystem(aoi_crs)
    geom = QgsGeometry.fromWkt(aoi_wkt).boundingBox()

    if not aoi_crs_obj.isValid():
        logger.warning("Invalid CRS for area of interest: %s.", aoi_crs)
        return None

    if geom.isNull() or geom.isEmpty():
        logger.warning("Failed to parse area of interest WKT: %s.", aoi_wkt)
        return None

    try:
        return reproject_extent(geom, aoi_crs_obj)
    except ValueError as error:
        logger.warning(
            "Failed to reproject the area of interest from %s to EPSG:4326. Error: %s.",
            aoi_crs,
            error,
        )
        return None


def _extract_project_details(project: QgsProject) -> ProjectDetails:
    """Extract project details."""
    logger.info("Extract project details…")
    logger.info("Reading QGIS project file…")

    details: ProjectDetails = cast("ProjectDetails", {})
    tmp_project_details = open_qgis_project_temporarily(project.fileName())
    tmp_project = tmp_project_details["project"]

    # NOTE force delete the `QgsProject`, otherwise the `QgsApplication` might be deleted by the time the project is garbage collected
    del tmp_project

    extent_wkt = ""
    project_crs = project.crs()
    try:
        reprojected_extent = reproject_extent(
            tmp_project_details["map_settings"].extent(), project_crs
        )
        extent_wkt = reprojected_extent.asWktPolygon()
    except ValueError as error:
        logger.warning(
            "Failed to reproject the project extent from %s to EPSG:4326. Error: %s.",
            project_crs.authid(),
            error,
        )

    area_of_interest = _get_area_of_interest(project)
    area_of_interest_wkt = ""
    if area_of_interest:
        area_of_interest_wkt = area_of_interest.asWktPolygon()

    details["background_color"] = tmp_project_details["background_color"]
    details["extent"] = extent_wkt
    details["area_of_interest"] = area_of_interest_wkt
    details["crs"] = project_crs.authid()
    details["project_name"] = project.title()

    logger.info("Extracting layer and datasource details…")

    details["layers_by_id"] = get_layers_data(project)
    details["ordered_layer_ids"] = list(details["layers_by_id"].keys())
    details["attachment_dirs"], _ = project.readListEntry(
        "QFieldSync", "attachmentDirs", ["DCIM"]
    )
    details["data_dirs"], _ = project.readListEntry("QFieldSync", "dataDirs", [])
    # NOTE we are at quite far in the process of working with the QGIS project file, so we can safely assume that
    # if the project file was broken, we would have already thrown an error before, so no need to try/except for `ValueError` here.
    details["qgis_version"] = get_qgis_version_from_project_file(project.fileName())

    logger.info(
        f"QGIS project layer checks\n{layers_data_to_string(details['layers_by_id'])}",
    )

    return details


def _generate_thumbnail(
    the_qgis_file_name: str,
    thumbnail_filename: Path,
    thumbnail_timeout_s: int = THUMBNAIL_TIMEOUT_S,
) -> Path | None:
    """
    Create a thumbnail for the project.

    As from https://docs.qgis.org/3.16/en/docs/pyqgis_developer_cookbook/composer.html#simple-rendering
    """
    logger.info("Generate project thumbnail image…")

    tmp_project_details = open_qgis_project_temporarily(the_qgis_file_name)
    tmp_project = tmp_project_details["project"]
    map_settings = tmp_project_details["map_settings"]

    if map_settings.extent().isEmpty():
        logger.warning(
            "Project has empty extent, using the full extent for the thumbnail."
        )

        map_settings.setExtent(map_settings.fullExtent())

    # NOTE when the extent is still empty, QGIS hangs forever, so we just skip thumbnail generation.
    if map_settings.extent().isEmpty():
        logger.warning("Project has empty extent, no thumbnail can be generated.")

        # NOTE force delete the `QgsProject`, otherwise the `QgsApplication` might be deleted by the time the project is garbage collected.
        del tmp_project

        return None

    img = QImage(map_settings.outputSize(), QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    job = QgsMapRendererCustomPainterJob(map_settings, painter)

    def on_timeout():
        nonlocal job

        logger.warning(
            f"Thumbnail generation timeout {thumbnail_timeout_s} seconds reached, cancelling the job..."
        )

        job.cancel()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(thumbnail_timeout_s * 1000)
    timer.timeout.connect(on_timeout)

    job.start()
    timer.start()

    if job.isActive():
        job.waitForFinishedWithEventLoop()
        is_thumbnail_generated = True
    else:
        logger.info("Job is not active, skipping wait for finished with event loop.")

        is_thumbnail_generated = False

    timer.stop()

    if is_thumbnail_generated:
        if not img.save(str(thumbnail_filename)):
            raise FailedThumbnailGenerationError(
                reason=f"Failed to save thumbnail to {thumbnail_filename}."
            )

    painter.end()

    # NOTE force delete the `QgsMapRendererCustomPainterJob`, `QPainter` and `QImage` because we are paranoid with Cpp objects around
    del job
    del painter
    del img
    # NOTE force delete the `QgsProject`, otherwise the `QgsApplication` might be deleted by the time the project is garbage collected
    del tmp_project

    if is_thumbnail_generated:
        logger.info("Project thumbnail image generated!")

        return thumbnail_filename
    else:
        logger.warning("Project thumbnail image could not be generated.")

        return None


class ProcessProjectfileCommand(QfcBaseCommand):
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("project_id", type=UUID, help="Project ID")
        parser.add_argument("project_file", type=str, help="QGIS project file path")

    def get_workflow(self, project_id: UUID, project_file: str) -> Workflow:  # type: ignore
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
                        "thumbnail_filename": WorkDirPath("thumbnail.png"),
                    },
                    method=_generate_thumbnail,
                    return_names=["thumbnail_filename"],
                ),
                Step(
                    id="upload_thumbnail",
                    name="Upload Thumbnail Image",
                    arguments={
                        "project_id": project_id,
                        "thumbnail_filename": StepOutput(
                            "generate_thumbnail_image", "thumbnail_filename"
                        ),
                    },
                    method=upload_project_thumbnail,
                ),
                Step(
                    id="stop_qgis_app",
                    name="Stop QGIS Application",
                    method=stop_app,
                ),
            ],
        )

        return workflow


cmd = ProcessProjectfileCommand()

if __name__ == "__main__":
    cmd.run_from_argv()
