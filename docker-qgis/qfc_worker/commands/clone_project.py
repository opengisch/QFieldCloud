import argparse
import logging
from pathlib import Path
from uuid import UUID

from qfc_worker.commands.create_project import (
    ProjectSeed,
    extract_layer_data,
    get_project_seed,
)
from qfc_worker.commands_base import QfcBaseCommand
from qfc_worker.utils import (
    download_project,
    start_app,
    stop_app,
    upload_project,
)
from qfc_worker.workflow import (
    Step,
    StepOutput,
    WorkDirPath,
    Workflow,
)

logger = logging.getLogger(__name__)


def download_source_project(project_seed: ProjectSeed, tmp_work_dir: Path) -> Path:
    """Download the source project files into the work directory.

    Uses the `copy_from_project` UUID from the project seed to identify
    the source project, then downloads all files (including attachments)
    into `tmp_work_dir/files/`.
    """
    if not project_seed.copy_from_project:
        raise ValueError(
            "Cannot clone project: `copy_from_project` is not set in the project seed."
        )

    source_project_id = str(project_seed.copy_from_project)

    logger.info(
        f"Downloading source project {source_project_id} into {tmp_work_dir}..."
    )

    download_project(
        source_project_id,
        destination=tmp_work_dir,
        skip_attachments=False,
    )

    logger.info("Source project files downloaded successfully.")

    return tmp_work_dir


def find_qgis_project_file(tmp_work_dir: Path) -> str | None:
    """Locate the QGIS project file (.qgz or .qgs) in the downloaded files."""
    files_dir = tmp_work_dir.joinpath("files")

    for pattern in ("*.qgz", "*.qgs"):
        matches = list(files_dir.glob(pattern))
        if matches:
            logger.info(f"Found QGIS project file: {matches[0]}")
            return str(matches[0])

    logger.warning("No QGIS project file found in downloaded files.")
    return None


class CloneProjectCommand(QfcBaseCommand):
    command_help = "Clone an existing project by copying all its files to a new project"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "project_id", type=UUID, help="New (destination) Project ID"
        )

    def get_workflow(self, project_id: UUID) -> Workflow:  # type: ignore
        workflow = Workflow(
            id="clone_project",
            name="Clone Project",
            version="1.0",
            steps=[
                Step(
                    id="start_qgis_app",
                    name="Start QGIS Application",
                    method=start_app,
                    return_names=["qgis_version"],
                ),
                Step(
                    id="get_project_seed",
                    name="Get Project Seed",
                    arguments={
                        "project_id": project_id,
                    },
                    method=get_project_seed,
                    return_names=["project_seed"],
                ),
                Step(
                    id="download_source_project",
                    name="Download Source Project Files",
                    arguments={
                        "project_seed": StepOutput("get_project_seed", "project_seed"),
                        "tmp_work_dir": WorkDirPath(),
                    },
                    method=download_source_project,
                    return_names=["work_dir"],
                ),
                Step(
                    id="find_qgis_project_file",
                    name="Find QGIS Project File",
                    arguments={
                        "tmp_work_dir": StepOutput(
                            "download_source_project", "work_dir"
                        ),
                    },
                    method=find_qgis_project_file,
                    return_names=["qgis_project_file"],
                ),
                Step(
                    id="qgis_layers_data",
                    name="QGIS Layers Data",
                    arguments={
                        "the_qgis_file_name": StepOutput(
                            "find_qgis_project_file", "qgis_project_file"
                        ),
                    },
                    method=extract_layer_data,
                    return_names=["layers_by_id"],
                    outputs=["layers_by_id"],
                ),
                Step(
                    id="upload_project_directory",
                    name="Upload Cloned Project",
                    arguments={
                        "project_id": project_id,
                        "project_dir": WorkDirPath("files"),
                    },
                    method=upload_project,
                ),
                Step(
                    id="stop_qgis_app",
                    name="Stop QGIS Application",
                    method=stop_app,
                ),
            ],
        )

        return workflow


cmd = CloneProjectCommand()

if __name__ == "__main__":
    cmd.run_from_argv()
