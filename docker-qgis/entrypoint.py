#!/usr/bin/env python3

import argparse
import hashlib
import logging
import os
import tempfile
from pathlib import Path, PurePath
from typing import Dict, Union

import boto3
import qfieldcloud.qgis.apply_deltas
import qfieldcloud.qgis.process_projectfile
from libqfieldsync.offline_converter import ExportType, OfflineConverter
from libqfieldsync.project import ProjectConfiguration
from libqfieldsync.utils.file_utils import get_project_in_folder
from qfieldcloud.qgis.utils import (
    Step,
    StepOutput,
    WorkDirPath,
    Workflow,
    get_layers_data,
    layers_data_to_string,
    start_app,
    stop_app,
)
from qgis.core import (
    QgsCoordinateTransform,
    QgsOfflineEditing,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

# Get environment variables
STORAGE_ACCESS_KEY_ID = os.environ.get("STORAGE_ACCESS_KEY_ID")
STORAGE_SECRET_ACCESS_KEY = os.environ.get("STORAGE_SECRET_ACCESS_KEY")
STORAGE_BUCKET_NAME = os.environ.get("STORAGE_BUCKET_NAME")
STORAGE_REGION_NAME = os.environ.get("STORAGE_REGION_NAME")
STORAGE_ENDPOINT_URL = os.environ.get("STORAGE_ENDPOINT_URL")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get_s3_resource():
    """Get S3 Service Resource object"""
    # Create session
    session = boto3.Session(
        aws_access_key_id=STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=STORAGE_SECRET_ACCESS_KEY,
        region_name=STORAGE_REGION_NAME,
    )

    return session.resource("s3", endpoint_url=STORAGE_ENDPOINT_URL)


def _get_s3_bucket():
    """Get S3 Bucket according to the env variable
    STORAGE_BUCKET_NAME"""

    s3 = _get_s3_resource()
    bucket = s3.Bucket(STORAGE_BUCKET_NAME)
    return bucket


def _get_sha256sum(filepath):
    """Calculate sha256sum of a file"""
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    with filepath as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()


def _get_md5sum(filepath):
    """Calculate sha256sum of a file"""
    BLOCKSIZE = 65536
    hasher = hashlib.md5()
    with filepath as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()


def _download_project_directory(project_id: str, download_dir: Path = None) -> Path:
    """Download the files in the project "working" directory from the S3
    Storage into a temporary directory. Returns the directory path"""

    bucket = _get_s3_bucket()

    # Prefix of the working directory on the Storages
    working_prefix = "/".join(["projects", project_id, "files"])

    if not download_dir:
        # Create a temporary directory
        download_dir = Path(tempfile.mkdtemp())

    # Create a local working directory
    working_dir = download_dir.joinpath("files")
    working_dir.mkdir(parents=True)

    # Download the files
    for obj in bucket.objects.filter(Prefix=working_prefix):
        key_filename = PurePath(obj.key)

        # Get the path of the file relative to the project directory
        relative_filename = key_filename.relative_to(*key_filename.parts[:2])
        absolute_filename = download_dir.joinpath(relative_filename)
        absolute_filename.parent.mkdir(parents=True, exist_ok=True)

        logging.info(
            f'Downloading file "{obj.key}", size: {obj.size} bytes, md5sum: "{obj.e_tag}" '
        )

        bucket.download_file(obj.key, str(absolute_filename))

    return download_dir


def _upload_project_directory(
    project_id: str, local_dir: Path, should_delete: bool = False
) -> None:
    """Upload the files in the local_dir to the storage"""
    stop_app()

    bucket = _get_s3_bucket()
    # either "files" or "package"
    subdir = local_dir.parts[-1]
    prefix = "/".join(["projects", project_id, subdir])

    if should_delete:
        # Remove existing package directory on the storage
        bucket.objects.filter(Prefix=prefix).delete()

    # Loop recursively in the local package directory
    for elem in Path(local_dir).rglob("*.*"):
        # Don't upload .qgs~ and .qgz~ files
        if str(elem).endswith("~"):
            continue
        # Don't upload qfieldcloud backup files
        if str(elem).endswith(".qfieldcloudbackup"):
            continue

        # Calculate sha256sum
        with open(elem, "rb") as e:
            sha256sum = _get_sha256sum(e)

        with open(elem, "rb") as e:
            md5sum = _get_md5sum(e)

        # Create the key
        filename = str(elem.relative_to(*elem.parts[:4]))
        key = "/".join([prefix, filename])
        metadata = {"sha256sum": sha256sum}

        if should_delete:
            storage_metadata = {"sha256sum": None}
        else:
            storage_metadata = bucket.Object(key).metadata
            storage_metadata["sha256sum"] = storage_metadata.get(
                "sha256sum", storage_metadata.get("Sha256sum", None)
            )

        # Check if the file is different on the storage
        # TODO switch to etag/md5sum comparison
        if metadata["sha256sum"] != storage_metadata["sha256sum"]:
            logging.info(
                f'Uploading file "{key}", size: {elem.stat().st_size} bytes, md5sum: {md5sum}, sha256sum: "{sha256sum}" '
            )
            bucket.upload_file(str(elem), key, ExtraArgs={"Metadata": metadata})


def _call_qfieldsync_packager(project_filename: Path, package_dir: Path) -> str:
    """Call the function of QFieldSync to package a project for QField"""

    start_app()

    project = QgsProject.instance()
    if not project_filename.exists():
        raise FileNotFoundError(project_filename)

    if not project.read(str(project_filename)):
        raise Exception(f"Unable to open file with QGIS: {project_filename}")

    layers = project.mapLayers()
    project_config = ProjectConfiguration(project)
    vl_extent_wkt = QgsRectangle()
    vl_extent_crs = project.crs().authid()

    if project_config.area_of_interest and project_config.area_of_interest_crs:
        vl_extent_wkt = project_config.area_of_interest
        vl_extent_crs = project_config.area_of_interest_crs
    else:
        vl_extent = QgsRectangle()
        for layer in layers.values():
            if type(layer) != QgsVectorLayer:
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
                vl_extent = qfieldcloud.qgis.utils.extract_project_details(project)[
                    "extent"
                ]
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
        vl_extent_crs = project.crs().authid()

    offline_editing = QgsOfflineEditing()
    offline_converter = OfflineConverter(
        project,
        str(package_dir),
        vl_extent_wkt,
        vl_extent_crs,
        offline_editing,
        export_type=ExportType.Cloud,
        create_basemap=False,
    )

    # Disable the basemap generation because it needs the processing
    # plugin to be installed
    offline_converter.project_configuration.create_base_map = False
    offline_converter.convert()

    packaged_project_filename = get_project_in_folder(str(package_dir))
    if Path(packaged_project_filename).stat().st_size == 0:
        raise Exception("The packaged QGIS project file is empty.")

    return packaged_project_filename


def _extract_layer_data(project_filename: Union[str, Path]) -> Dict:
    start_app()

    project_filename = str(project_filename)
    project = QgsProject.instance()
    project.read(project_filename)
    layers_by_id = get_layers_data(project)

    logging.info(
        f"QGIS project layer checks\n{layers_data_to_string(layers_by_id)}",
    )

    return layers_by_id


def cmd_package_project(args):
    workflow = Workflow(
        id="package_project",
        name="Package Project",
        version="2.0",
        description="Packages a QGIS project to be used on QField. Converts layers for offline editing if configured.",
        steps=[
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "download_dir": WorkDirPath(mkdir=True),
                },
                method=_download_project_directory,
                return_names=["tmp_project_dir"],
            ),
            Step(
                id="qgis_layers_data",
                name="QGIS Layers Data",
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
                },
                method=_call_qfieldsync_packager,
                return_names=["qfield_project_filename"],
            ),
            Step(
                id="qfield_layer_data",
                name="Packaged Layers Data",
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
                id="upload_packaged_project",
                name="Upload Packaged Project",
                arguments={
                    "project_id": args.projectid,
                    "local_dir": WorkDirPath("export", mkdir=True),
                    "should_delete": True,
                },
                method=_upload_project_directory,
            ),
        ],
    )

    qfieldcloud.qgis.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


def _apply_delta(args):
    workflow = Workflow(
        id="apply_changes",
        name="Apply Changes",
        version="2.0",
        steps=[
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "download_dir": WorkDirPath(mkdir=True),
                },
                method=_download_project_directory,
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
                method=qfieldcloud.qgis.apply_deltas.delta_apply,
                return_names=["delta_feedback"],
                outputs=["delta_feedback"],
            ),
            Step(
                id="upload_exported_project",
                name="Upload Project",
                arguments={
                    "project_id": args.projectid,
                    "local_dir": WorkDirPath("files"),
                    "should_delete": False,
                },
                method=_upload_project_directory,
            ),
        ],
    )

    qfieldcloud.qgis.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


def cmd_process_projectfile(args):
    workflow = Workflow(
        id="process_projectfile",
        name="Process Projectfile",
        version="2.0",
        steps=[
            Step(
                id="download_project_directory",
                name="Download Project Directory",
                arguments={
                    "project_id": args.projectid,
                    "download_dir": WorkDirPath(mkdir=True),
                },
                method=_download_project_directory,
                return_names=["tmp_project_dir"],
            ),
            Step(
                id="project_validity_check",
                name="Project Validity Check",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=qfieldcloud.qgis.process_projectfile.check_valid_project_file,
            ),
            Step(
                id="opening_check",
                name="Opening Check",
                arguments={
                    "project_filename": WorkDirPath("files", args.project_file),
                },
                method=qfieldcloud.qgis.process_projectfile.load_project_file,
                return_names=["project"],
            ),
            Step(
                id="project_details",
                name="Project Details",
                arguments={
                    "project": StepOutput("opening_check", "project"),
                },
                method=qfieldcloud.qgis.process_projectfile.extract_project_details,
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
                method=qfieldcloud.qgis.process_projectfile.generate_thumbnail,
            ),
        ],
    )

    qfieldcloud.qgis.utils.run_workflow(
        workflow,
        Path("/io/feedback.json"),
    )


if __name__ == "__main__":

    # Set S3 logging levels
    logging.getLogger("boto3").setLevel(logging.CRITICAL)
    logging.getLogger("botocore").setLevel(logging.CRITICAL)
    logging.getLogger("nose").setLevel(logging.CRITICAL)
    logging.getLogger("s3transfer").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)

    parser = argparse.ArgumentParser(prog="COMMAND")

    subparsers = parser.add_subparsers(dest="cmd")

    parser_package = subparsers.add_parser("package", help="Package a project")
    parser_package.add_argument("projectid", type=str, help="projectid")
    parser_package.add_argument("project_file", type=str, help="QGIS project file path")
    parser_package.set_defaults(func=cmd_package_project)

    parser_delta = subparsers.add_parser("delta_apply", help="Apply deltafile")
    parser_delta.add_argument("projectid", type=str, help="projectid")
    parser_delta.add_argument("project_file", type=str, help="QGIS project file path")
    parser_delta.add_argument(
        "--overwrite-conflicts", dest="overwrite_conflicts", action="store_true"
    )
    parser_delta.add_argument("--inverse", dest="inverse", action="store_true")
    parser_delta.set_defaults(func=_apply_delta)

    parser_process_projectfile = subparsers.add_parser(
        "process_projectfile", help="Process QGIS project file"
    )
    parser_process_projectfile.add_argument("projectid", type=str, help="projectid")
    parser_process_projectfile.add_argument(
        "project_file", type=str, help="QGIS project file path"
    )
    parser_process_projectfile.set_defaults(func=cmd_process_projectfile)

    args = parser.parse_args()
    args.func(args)
