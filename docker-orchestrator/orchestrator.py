import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import List

import docker
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
from psycopg2 import connect

psycopg2.extras.register_uuid()

logger = logging.getLogger(__name__)

QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
TMP_DIRECTORY = os.environ.get("TMP_DIRECTORY", None)

assert QGIS_CONTAINER_NAME
assert TMP_DIRECTORY


class QgisException(Exception):
    pass


class ApplyDeltaScriptException(Exception):
    pass


def get_django_db_connection(is_test_db=False):
    """Connect to the Django db. If the param is_test_db is true
    it will try to connect to the temporary test db.
    Return the connection or None"""

    dbname = os.environ.get("POSTGRES_DB")
    if is_test_db:
        dbname = "test_" + dbname

    try:
        conn = connect(
            dbname=dbname,
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD"),
            host=os.environ.get("POSTGRES_HOST"),
            port=os.environ.get("POSTGRES_PORT"),
        )
    except psycopg2.OperationalError:
        return None

    return conn


def export_project(job_id, project_file):
    """Start a QGIS docker container to export the project using libqfieldsync """

    logger.info(f"Starting a new export for project {job_id}")

    project_id = get_job_row(job_id)["project_id"]
    orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
    qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)

    volumes = {qgis_tempdir: {"bind": "/io/", "mode": "rw"}}

    update_job(job_id, JobStatus.STARTED)

    # If we are on local dev environment, use host network to connect
    # to the local geodb and s3 storage
    network_mode = "bridge"
    if os.environ.get("QFIELDCLOUD_HOST") == "localhost":
        network_mode = "host"

    client = docker.from_env()
    container = client.containers.create(
        QGIS_CONTAINER_NAME,
        environment={
            "STORAGE_ACCESS_KEY_ID": os.environ.get("STORAGE_ACCESS_KEY_ID"),
            "STORAGE_SECRET_ACCESS_KEY": os.environ.get("STORAGE_SECRET_ACCESS_KEY"),
            "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
            "STORAGE_REGION_NAME": os.environ.get("STORAGE_REGION_NAME"),
            "STORAGE_ENDPOINT_URL": os.environ.get("STORAGE_ENDPOINT_URL"),
        },
        auto_remove=True,
        volumes=volumes,
        network_mode=network_mode,
    )

    container.start()
    container.attach(logs=True)
    container_command = (
        f"xvfb-run python3 entrypoint.py export {project_id} {project_file}"
    )
    exit_code, output = container.exec_run(container_command)
    container.kill()

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


def deltas_to_deltafile(
    job_id: str, project_id: str, delta_ids: List[str], filename: Path
) -> None:
    deltas = update_deltas(job_id, delta_ids, DeltaStatus.STARTED)

    json_content = {
        "deltas": [delta["content"] for delta in deltas],
        "files": [],
        "id": str(uuid.uuid4()),
        "project": str(project_id),
        "version": "1.0",
    }

    with open(filename, "w") as f:
        json.dump(json_content, f)


def apply_deltas(job_id, project_file):
    """Start a QGIS docker container to apply a deltafile using the
    apply-delta script"""

    logger.info(f"Starting a new delta apply job {job_id}")

    job_row = get_job_row(job_id)
    project_id = job_row["project_id"]
    overwrite_conflicts = job_row["project_id"]
    orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
    qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)
    delta_ids = get_deltas_to_apply_list(job_id)
    deltafile_path = qgis_tempdir.joinpath("deltafile.json")

    deltas_to_deltafile(job_id, project_id, delta_ids, deltafile_path)

    volumes = {qgis_tempdir: {"bind": "/io/", "mode": "rw"}}

    # If we are on local dev environment, use host network to connect
    # to the local geodb and s3 storage
    network_mode = "bridge"
    if os.environ.get("QFIELDCLOUD_HOST") == "localhost":
        network_mode = "host"

    client = docker.from_env()
    container = client.containers.create(
        QGIS_CONTAINER_NAME,
        environment={
            "STORAGE_ACCESS_KEY_ID": os.environ.get("STORAGE_ACCESS_KEY_ID"),
            "STORAGE_SECRET_ACCESS_KEY": os.environ.get("STORAGE_SECRET_ACCESS_KEY"),
            "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
            "STORAGE_REGION_NAME": os.environ.get("STORAGE_REGION_NAME"),
            "STORAGE_ENDPOINT_URL": os.environ.get("STORAGE_ENDPOINT_URL"),
        },
        auto_remove=True,
        volumes=volumes,
        network_mode=network_mode,
    )

    overwrite_conflicts_cmd = ""
    if overwrite_conflicts:
        overwrite_conflicts_cmd = "--overwrite-conflicts"

    container.start()
    container.attach(logs=True)
    container_command = "xvfb-run python3 entrypoint.py apply-delta {} {} {}".format(
        project_id, project_file, overwrite_conflicts_cmd
    )

    exit_code, output = container.exec_run(container_command)
    container.kill()

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

    # if exit_code not in [0, 1]:
    #     raise ApplyDeltaScriptException(output)
    return exit_code, output.decode("utf-8")


def check_status():
    """Launch a container to check that everything is working
    correctly."""

    client = docker.from_env()
    container = client.containers.create(
        QGIS_CONTAINER_NAME,
        environment={
            "STORAGE_ACCESS_KEY_ID": os.environ.get("STORAGE_ACCESS_KEY_ID"),
            "STORAGE_SECRET_ACCESS_KEY": os.environ.get("STORAGE_SECRET_ACCESS_KEY"),
            "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
            "STORAGE_REGION_NAME": os.environ.get("STORAGE_REGION_NAME"),
            "STORAGE_ENDPOINT_URL": os.environ.get("STORAGE_ENDPOINT_URL"),
        },
        # TODO: environment=load_env_file(),
        auto_remove=True,
    )

    container.start()
    container.attach(logs=True)

    # TODO: create a command to actually start qgis and check some features
    container_command = "echo QGIS container is running"

    exit_code, output = container.exec_run(container_command)
    container.kill()

    logger.info(
        "check_status, exit_code: {}, output:\n\n{}".format(
            exit_code, output.decode("utf-8")
        )
    )

    if not exit_code == 0:
        raise QgisException(output)
    return exit_code, output.decode("utf-8")
