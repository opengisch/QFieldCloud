#!/usr/bin/env python3

import argparse
import logging
import os
from pathlib import Path

import qfc_worker.apply_deltas
import qfc_worker.package
import qfc_worker.process_projectfile
import qfc_worker.utils
from libqfieldsync.offliners import OfflinerType
from qfc_worker.utils import (
    Step,
    StepOutput,
    WorkDirPath,
    WorkDirPathAsStr,
    Workflow,
)

PGSERVICE_FILE_CONTENTS = os.environ.get("PGSERVICE_FILE_CONTENTS")

logger = logging.getLogger("ENTRYPNT")
logger.setLevel(logging.INFO)


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
                return_names=["qgis_version"],
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
                id="qgis_layers_data",
                name="QGIS Layers Data",
                arguments={
                    "the_qgis_file_name": WorkDirPath("files", args.project_file),
                },
                method=qfc_worker.package.extract_layer_data,
                return_names=["layers_by_id"],
                outputs=["layers_by_id"],
            ),
            Step(
                id="package_project",
                name="Package Project",
                arguments={
                    "the_qgis_file_name": WorkDirPath("files", args.project_file),
                    "package_dir": WorkDirPath("export", mkdir=True),
                    "offliner_type": args.offliner_type,
                },
                method=qfc_worker.package.call_libqfieldsync_packager,
                return_names=["the_qgis_file_name_in_qfield"],
            ),
            Step(
                id="qfield_layer_data",
                name="Packaged Layers Data",
                arguments={
                    "the_qgis_file_name": StepOutput(
                        "package_project", "the_qgis_file_name_in_qfield"
                    ),
                },
                method=qfc_worker.package.extract_layer_data,
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
                return_names=["qgis_version"],
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
                    "the_qgis_file_name": WorkDirPath("files", args.project_file),
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
                return_names=["qgis_version"],
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
                    "the_qgis_file_name": WorkDirPath("files", args.project_file),
                },
                method=qfc_worker.process_projectfile.check_valid_project_file,
            ),
            Step(
                id="opening_check",
                name="Opening Check",
                arguments={
                    "the_qgis_file_name": WorkDirPathAsStr("files", args.project_file),
                    "force_reload": True,
                    "disable_feature_count": True,
                },
                method=qfc_worker.utils.open_qgis_project_as_readonly,
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
                    "the_qgis_file_name": WorkDirPathAsStr("files", args.project_file),
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


def main() -> None:
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


if __name__ == "__main__":
    main()
