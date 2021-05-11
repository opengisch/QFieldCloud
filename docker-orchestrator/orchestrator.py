import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
from db_utils import (
    DeltaStatus,
    JobStatus,
    get_deltas_to_apply_list,
    get_job_row,
    update_deltas,
    update_job,
)
from docker_utils import run_docker

psycopg2.extras.register_uuid()

logger = logging.getLogger(__name__)

TMP_DIRECTORY = os.environ.get("TMP_DIRECTORY", None)

assert TMP_DIRECTORY


class QgisException(Exception):
    pass


def export_project(job_id, project_file):
    """Start a QGIS docker container to export the project using libqfieldsync """

    logger.info(f"Starting a new export for project {job_id}")

    project_id = get_job_row(job_id)["project_id"]
    orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
    qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)

    update_job(job_id, JobStatus.STARTED)

    exit_code, output = run_docker(
        f"xvfb-run python3 entrypoint.py export {project_id} {project_file}",
        volumes={qgis_tempdir: {"bind": "/io/", "mode": "rw"}},
    )

    logger.info(
        "export_project, projectid: {}, project_file: {}, exit_code: {}, output:\n\n{}".format(
            project_id, project_file, exit_code, output.decode("utf-8")
        )
    )

    if not exit_code == 0:
        update_job(job_id, JobStatus.FAILED, output=output.decode("utf-8"))

        raise QgisException(output)

    exportlog_file = os.path.join(orchestrator_tempdir, "exportlog.json")

    try:
        with open(exportlog_file, "r") as f:
            exportlog = json.load(f)
    except FileNotFoundError:
        exportlog = "Export log not available"

    update_job(
        job_id, JobStatus.FINISHED, exportlog=exportlog, output=output.decode("utf-8")
    )

    return exit_code, output.decode("utf-8"), exportlog


def apply_deltas(job_id, project_file):
    """Start a QGIS docker container to apply a deltafile using the
    apply-delta script"""

    logger.info(f"Starting a new delta apply job {job_id}")

    job_row = get_job_row(job_id)
    project_id = job_row["project_id"]
    overwrite_conflicts = job_row["overwrite_conflicts"]
    orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
    qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)
    delta_ids = get_deltas_to_apply_list(job_id)
    deltas = update_deltas(job_id, delta_ids, DeltaStatus.STARTED)

    json_content = {
        "deltas": [delta["content"] for delta in deltas],
        "files": [],
        "id": str(uuid.uuid4()),
        "project": str(project_id),
        "version": "1.0",
    }

    with open(qgis_tempdir.joinpath("deltafile.json"), "w") as f:
        json.dump(json_content, f)

    overwrite_conflicts_arg = "--overwrite-conflicts" if overwrite_conflicts else ""
    exit_code, output = run_docker(
        f"xvfb-run python3 entrypoint.py apply-delta {project_id} {project_file} {overwrite_conflicts_arg}",
        volumes={qgis_tempdir: {"bind": "/io/", "mode": "rw"}},
    )

    logger.info(
        f"""
===============================================================================
| Apply deltas finished
===============================================================================
Project ID: {project_id}
Project file: {project_file}
Exit code: {exit_code}
Output:
------------------------------------------------------------------------------S
{output.decode('utf-8')}
------------------------------------------------------------------------------E
"""
    )

    deltalog_file = os.path.join(orchestrator_tempdir, "deltalog.json")
    with open(deltalog_file, "r") as f:
        deltalog = json.load(f)

        for feedback in deltalog:
            delta_id = feedback["delta_id"]
            status = feedback["status"]

            if status == "status_applied":
                status = DeltaStatus.APPLIED
            elif status == "status_conflict":
                status = DeltaStatus.CONFLICT
            elif status == "status_apply_failed":
                status = DeltaStatus.NOT_APPLIED
            else:
                status = DeltaStatus.ERROR

            update_deltas(job_id, [delta_id], status, feedback)

    return exit_code, output.decode("utf-8")


def check_status():
    """Launch a container to check that everything is working
    correctly."""

    exit_code, output = run_docker('echo "QGIS container is running"')

    logger.info(
        "check_status, exit_code: {}, output:\n\n{}".format(
            exit_code, output.decode("utf-8")
        )
    )

    if not exit_code == 0:
        raise QgisException(output)
    return exit_code, output.decode("utf-8")
