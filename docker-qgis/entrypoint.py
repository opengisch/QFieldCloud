#!/usr/bin/env python3

import argparse
import logging
import os
from pathlib import Path
from typing import Union

import qfc_worker.apply_deltas
import qfc_worker.process_projectfile
from libqfieldsync.offline_converter import ExportType, OfflineConverter
from libqfieldsync.offliners import OfflinerType, PythonMiniOffliner, QgisCoreOffliner
from libqfieldsync.project import ProjectConfiguration
from libqfieldsync.utils.bad_layer_handler import set_bad_layer_handler
from libqfieldsync.utils.file_utils import get_project_in_folder
from qfc_worker.utils import (
    Step,
    StepOutput,
    WorkDirPath,
    Workflow,
    get_layers_data,
    layers_data_to_string,
)
from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle, QgsVectorLayer

PGSERVICE_FILE_CONTENTS = os.environ.get("PGSERVICE_FILE_CONTENTS")

logger = logging.getLogger("ENTRYPNT")
logger.setLevel(logging.INFO)


def _call_libqfieldsync_packager(
    project_filename: Path, package_dir: Path, offliner_type: OfflinerType
) -> str:
    """Call `libqfieldsync` to package a project for QField"""
    logger.info("Preparing QGIS project for packaging…")

    if not project_filename.exists():
        raise FileNotFoundError(project_filename)

    project = QgsProject.instance()

    project_filename_string = str(project_filename)
    if project.fileName() != project_filename_string:
        with set_bad_layer_handler(project):
            if not project.read(project_filename_string):
                project.setFileName("")
                raise Exception(f"Unable to open file with QGIS: {project_filename}")

    layers = project.mapLayers()
    project_config = ProjectConfiguration(project)
    vl_extent_wkt = QgsRectangle()
    vl_extent_crs = project.crs()

    logger.info("Getting project area of interest…")

    if project_config.area_of_interest and project_config.area_of_interest_crs:
        vl_extent_wkt = project_config.area_of_interest
        vl_extent_crs = project_config.area_of_interest_crs
    else:
        vl_extent = QgsRectangle()
        for layer in layers.values():
            if isinstance(layer, QgsVectorLayer):
                continue

            layer_extent = layer.extent()

            if layer_extent.isNull() or not layer_extent.isFinite():
                continue

            try:
                transform = QgsCoordinateTransform(layer.crs(), project.crs(), project)
                vl_extent.combineExtentWith(
                    transform.transformBoundingBox(layer_extent)
                )
            except Exception as err:
                logger.error(
                    "Failed to transform the bbox for layer {} from {} to {} CRS.".format(
                        layer.name(), layer.crs(), project.crs()
                    ),
                    exc_info=err,
                )

        if vl_extent.isNull() or not vl_extent.isFinite():
            logger.info("Failed to obtain the project extent from project layers.")

            try:
                vl_extent = qfc_worker.utils.extract_project_details(project)["extent"]
                vl_extent = QgsRectangle.fromWkt(vl_extent)
            except Exception as err:
                logger.error(
                    "Failed to get the project extent from the current map canvas.",
                    exc_info=err,
                )

        if vl_extent.isNull() or not vl_extent.isFinite():
            raise Exception("Failed to obtain the project extent.")

        # sometimes the result is a polygon whose all points are on the same line
        # this is an invalid polygon and cannot libqfieldsync does not like it
        vl_extent = vl_extent.buffered(1)
        vl_extent_wkt = vl_extent.asWktPolygon()
        vl_extent_crs = project.crs()

    logger.info(
        f"Project area of interest is `{vl_extent_wkt}` in `{vl_extent_crs}` CRS."
    )

    attachment_dirs, _ = project.readListEntry("QFieldSync", "attachmentDirs", ["DCIM"])
    if offliner_type == OfflinerType.QGISCORE:
        offliner = QgisCoreOffliner()
    elif offliner_type == OfflinerType.PYTHONMINI:
        offliner = PythonMiniOffliner()
    else:
        raise NotImplementedError(f"Offliner type {offliner_type} is not supported.")

    logger.info(f'Offliner set to "{offliner_type}"')

    logger.info("Packaging…")

    offline_converter = OfflineConverter(
        project,
        str(package_dir),
        vl_extent_wkt,
        vl_extent_crs,
        attachment_dirs,
        offliner=offliner,
        export_type=ExportType.Cloud,
        create_basemap=False,
    )

    # Disable the basemap generation because it needs the processing
    # plugin to be installed
    offline_converter.project_configuration.create_base_map = False
    offline_converter.convert(reload_original_project=False)

    logger.info("Packaging finished!")

    packaged_project_filename = get_project_in_folder(str(package_dir))
    if Path(packaged_project_filename).stat().st_size == 0:
        raise Exception("The packaged QGIS project file is empty.")

    return packaged_project_filename


def _extract_layer_data(project_filename: Union[str, Path]) -> dict:
    logger.info("Extracting QGIS project layer data…")

    project = QgsProject.instance()

    if project.fileName() != str(project_filename):
        with set_bad_layer_handler(project):
            if not project.read(str(project_filename)):
                project.setFileName("")
                raise Exception(f"Unable to open file with QGIS: {project_filename}")

    layers_by_id: dict = get_layers_data(project)

    logger.info(
        f"QGIS project layer data\n{layers_data_to_string(layers_by_id)}",
    )

    return layers_by_id


def _open_project(project_filename: Union[str, Path]):
    logger.info("Loading QGIS project…")

    project = QgsProject.instance()

    with set_bad_layer_handler(project):
        if not project.read(str(project_filename)):
            project.setFileName("")
            raise Exception(f"Unable to open project with QGIS: {project_filename}")

    logger.info("Project loaded.")


def cmd_package_project(args: argparse.Namespace):
    workflow = Workflow(
        id="package_project",
        name="Package Project",
        version="2.0",
        description="Packages a QGIS project to be used on QField. Converts layers for offline editing if configured.",
        steps=[
            Step(
                id="start_qgis_app",
                name="Start QGIS Application",
                method=qfc_worker.utils.start_app,
            ),
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "destination": WorkDirPath(mkdir=True),
                    "skip_attachments": True,
                },
                method=qfc_worker.utils.download_project,
                return_names=["tmp_project_dir"],
            ),
            Step(
                id="qgis_open_project",
                name="Open Project",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=_open_project,
            ),
            Step(
                id="qgis_layers_data",
                name="Original Project Layers Data",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=_extract_layer_data,
                return_names=["layers_by_id"],
                outputs=["layers_by_id"],
            ),
            Step(
                id="package_project",
                name="Package Project",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                    "package_dir": WorkDirPath("export", mkdir=True),
                    "offliner_type": args.offliner_type,
                },
                method=_call_libqfieldsync_packager,
                return_names=["qfield_project_filename"],
            ),
            Step(
                id="qfield_layer_data",
                name="Packaged Project Layers Data",
                arguments={
                    "project_filename": StepOutput(
                        "package_project", "qfield_project_filename"
                    ),
                },
                method=_extract_layer_data,
                return_names=["layers_by_id"],
                outputs=["layers_by_id"],
            ),
            Step(
                id="stop_qgis_app",
                name="Stop QGIS Application",
                method=qfc_worker.utils.stop_app,
            ),
            Step(
                id="upload_packaged_project",
                name="Upload Packaged Project",
                arguments={
                    "project_id": args.projectid,
                    "package_dir": WorkDirPath("export", mkdir=True),
                },
                method=qfc_worker.utils.upload_package,
            ),
        ],
    )

    qfc_worker.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


def cmd_apply_deltas(args: argparse.Namespace):
    workflow = Workflow(
        id="apply_changes",
        name="Apply Changes",
        version="2.0",
        steps=[
            Step(
                id="start_qgis_app",
                name="Start QGIS Application",
                method=qfc_worker.utils.start_app,
            ),
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "destination": WorkDirPath(mkdir=True),
                    "skip_attachments": True,
                },
                method=qfc_worker.utils.download_project,
                return_names=["tmp_project_dir"],
            ),
            Step(
                id="apply_deltas",
                name="Apply Deltas",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                    "delta_filename": "/io/deltafile.json",
                    "inverse": args.inverse,
                    "overwrite_conflicts": args.overwrite_conflicts,
                },
                method=qfc_worker.apply_deltas.delta_apply,
                return_names=["delta_feedback"],
                outputs=["delta_feedback"],
            ),
            Step(
                id="stop_qgis_app",
                name="Stop QGIS Application",
                method=qfc_worker.utils.stop_app,
            ),
            Step(
                id="upload_exported_project",
                name="Upload Project",
                arguments={
                    "project_id": args.projectid,
                    "project_dir": WorkDirPath("files"),
                },
                method=qfc_worker.utils.upload_project,
            ),
        ],
    )

    qfc_worker.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


def cmd_process_projectfile(args: argparse.Namespace):
    workflow = Workflow(
        id="process_projectfile",
        name="Process Projectfile",
        version="2.0",
        steps=[
            Step(
                id="start_qgis_app",
                name="Start QGIS Application",
                method=qfc_worker.utils.start_app,
            ),
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "destination": WorkDirPath(mkdir=True),
                    "skip_attachments": True,
                },
                method=qfc_worker.utils.download_project,
                return_names=["tmp_project_dir"],
            ),
            Step(
                id="project_validity_check",
                name="Project Validity Check",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=qfc_worker.process_projectfile.check_valid_project_file,
            ),
            Step(
                id="opening_check",
                name="Opening Check",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=qfc_worker.process_projectfile.load_project_file,
                return_names=["project"],
            ),
            Step(
                id="project_details",
                name="Project Details",
                arguments={
                    "project": StepOutput("opening_check", "project"),
                },
                method=qfc_worker.process_projectfile.extract_project_details,
                return_names=["project_details"],
                outputs=["project_details"],
            ),
            Step(
                id="generate_thumbnail_image",
                name="Generate Thumbnail Image",
                arguments={
                    "project": StepOutput("opening_check", "project"),
                    "thumbnail_filename": Path("/io/thumbnail.png"),
                },
                method=qfc_worker.process_projectfile.generate_thumbnail,
            ),
            Step(
                id="stop_qgis_app",
                name="Stop QGIS Application",
                method=qfc_worker.utils.stop_app,
            ),
        ],
    )

    qfc_worker.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


if __name__ == "__main__":
    from qfc_worker.utils import setup_basic_logging_config

    setup_basic_logging_config()

    # Set S3 logging levels
    logging.getLogger("nose").setLevel(logging.CRITICAL)
    logging.getLogger("s3transfer").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)

    if PGSERVICE_FILE_CONTENTS:
        with open(Path.home().joinpath(".pg_service.conf"), "w") as f:
            f.write(PGSERVICE_FILE_CONTENTS)

    parser = argparse.ArgumentParser(prog="COMMAND")

    subparsers = parser.add_subparsers(dest="cmd")

    parser_package = subparsers.add_parser("package", help="Package a project")
    parser_package.add_argument("projectid", type=str, help="projectid")
    parser_package.add_argument("project_file", type=str, help="QGIS project file path")
    parser_package.add_argument(
        "offliner_type",
        type=str,
        choices=(OfflinerType.QGISCORE, OfflinerType.PYTHONMINI),
        default=OfflinerType.QGISCORE,
    )
    parser_package.set_defaults(func=cmd_package_project)

    parser_delta = subparsers.add_parser("delta_apply", help="Apply deltafile")
    parser_delta.add_argument("projectid", type=str, help="projectid")
    parser_delta.add_argument("project_file", type=str, help="QGIS project file path")
    parser_delta.add_argument(
        "--overwrite-conflicts", dest="overwrite_conflicts", action="store_true"
    )
    parser_delta.add_argument("--inverse", dest="inverse", action="store_true")
    parser_delta.set_defaults(func=cmd_apply_deltas)

    parser_process_projectfile = subparsers.add_parser(
        "process_projectfile", help="Process QGIS project file"
    )
    parser_process_projectfile.add_argument("projectid", type=str, help="projectid")
    parser_process_projectfile.add_argument(
        "project_file", type=str, help="QGIS project file path"
    )
    parser_process_projectfile.set_defaults(func=cmd_process_projectfile)

    args: argparse.Namespace = parser.parse_args()
    args.func(args)
