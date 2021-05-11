import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Iterable, Optional

import docker
import psycopg2
from db_utils import JobStatus, get_job_row, update_job
from psycopg2 import connect

DELTA_STATUS_PENDING = (
    1  # deltafile has been received, but have not started application
)
DELTA_STATUS_BUSY = 2  # currently being applied
DELTA_STATUS_APPLIED = 3  # applied correctly
DELTA_STATUS_CONFLICT = 4  # needs conflict resolution
DELTA_STATUS_NOT_APPLIED = 5
DELTA_STATUS_ERROR = 6  # was not possible to apply the deltafile
DELTA_STATUS_IGNORED = 7  # delta is ignored

EXPORTATION_STATUS_PENDING = 1  # Export has been requested, but not yet started
EXPORTATION_STATUS_BUSY = 2  # Currently being exported
EXPORTATION_STATUS_EXPORTED = 3  # Export finished
EXPORTATION_STATUS_ERROR = 4  # was not possible to export the project


logger = logging.getLogger(__name__)

QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)

assert QGIS_CONTAINER_NAME


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
    qgis_tempdir = Path(os.environ.get("TMP_DIRECTORY")).joinpath(orchestrator_tempdir)

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


def set_delta_status_and_output(projectid, delta_id, status, output={}):
    """Set the deltafile status and output into the database record """

    conn = get_django_db_connection(True)
    if not conn:
        conn = get_django_db_connection(False)

    cur = conn.cursor()
    cur.execute(
        "UPDATE core_delta SET status = %s, updated_at = now(), output = %s WHERE id = %s AND project_id = %s",
        (status, json.dumps(output), delta_id, projectid),
    )
    conn.commit()

    cur.close()
    conn.close()


def create_deltafile_with_pending_deltas(
    projectid, tempdir, delta_ids: Optional[Iterable]
):
    """Retrieve the pending deltas from the db and create a deltafile-like
    json to be passed to the apply_deltas script"""

    conn = get_django_db_connection(is_test_db=True)
    if not conn:
        conn = get_django_db_connection(is_test_db=False)

    cur = conn.cursor()
    cur.execute(
        """
            SELECT
                id,
                deltafile_id,
                content
            FROM core_delta
            WHERE TRUE
                AND project_id = %s
                AND status = %s
                AND (%s IS NULL OR id::text = ANY(%s))
        """,
        (projectid, DELTA_STATUS_PENDING, delta_ids, delta_ids),
    )

    json_content = {
        "deltas": [],
        "files": [],
        "id": str(uuid.uuid4()),
        "project": projectid,
        "version": "1.0",
    }

    deltas = cur.fetchall()
    cur.close()
    conn.close()

    for delta in deltas:
        json_content["deltas"].append(delta[2])
        set_delta_status_and_output(projectid, delta[0], DELTA_STATUS_BUSY)

    deltafile = os.path.join(tempdir, "deltafile.json")
    with open(deltafile, "w") as f:
        json.dump(json_content, f)

    return deltafile


def apply_deltas(projectid, project_file, overwrite_conflicts, delta_ids):
    """Start a QGIS docker container to apply a deltafile unsing the
    apply-delta script"""

    orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
    qgis_tempdir = os.path.join(os.environ.get("TMP_DIRECTORY"), orchestrator_tempdir)

    logger.info(f"Starting a new export for project {projectid}")

    create_deltafile_with_pending_deltas(projectid, orchestrator_tempdir, delta_ids)

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
        projectid, project_file, overwrite_conflicts_cmd
    )

    exit_code, output = container.exec_run(container_command)
    container.kill()

    logger.info(
        f"""
===============================================================================
| Apply deltas finished
===============================================================================
Project ID: {projectid}
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

        for log in deltalog:
            delta_id = log["delta_id"]
            status = log["status"]
            if status == "status_applied":
                status = DELTA_STATUS_APPLIED
            elif status == "status_conflict":
                status = DELTA_STATUS_CONFLICT
            elif status == "status_apply_failed":
                status = DELTA_STATUS_NOT_APPLIED
            else:
                status = DELTA_STATUS_ERROR
            msg = log

            set_delta_status_and_output(projectid, delta_id, status, msg)

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
