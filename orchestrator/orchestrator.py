
import psycopg2
import logging
import json
import uuid
import tempfile
import os
from pathlib import Path

import docker


STATUS_PENDING = 1  # deltafile has been received, but have not started application
STATUS_BUSY = 2  # currently being applied
STATUS_APPLIED = 3  # applied correctly
STATUS_APPLIED_WITH_CONFLICTS = 4  # applied but needs conflict resolution
STATUS_NOT_APPLIED = 5
STATUS_ERROR = 6  # was not possible to apply the deltafile


class QgisException(Exception):
    pass


class ApplyDeltaScriptException(Exception):
    pass


def load_env_file():
    """Read env file and return a dict with the variables"""

    environment = {}
    with open('../.env') as f:
        for line in f:
            if line.strip():
                splitted = line.rstrip().split('=', maxsplit=1)
                environment[splitted[0]] = splitted[1]

    return environment


def export_project(projectid, project_file):
    """Start a QGIS docker container to export the project using QFieldSync """

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        environment=load_env_file(),
        auto_remove=True)

    container.start()
    container.attach(logs=True)
    container_command = 'xvfb-run python3 entrypoint.py export {} {}'.format(projectid, project_file)

    exit_code, output = container.exec_run(container_command)
    container.kill()

    logging.info(
        'export_project, projectid: {}, project_file: {}, exit_code: {}, output:\n\n{}'.format(
            projectid, project_file, exit_code, output.decode('utf-8')))

    if not exit_code == 0:
        raise QgisException(output)
    return exit_code, output.decode('utf-8')


def get_django_db_connection(is_test_db=False):
    """Connect to the Django db. If the param is_test_db is true
    it will try to connect to the temporary test db.
    Return the connection or None"""

    env = load_env_file()
    dbname = env.get('POSTGRES_DB')
    if is_test_db:
        dbname = 'test_' + dbname

    try:
        conn = psycopg2.connect(
            dbname=dbname,
            user=env.get('POSTGRES_USER'),
            password=env.get('POSTGRES_PASSWORD'),
            host=env.get('QFIELDCLOUD_HOST')
        )
    except psycopg2.OperationalError:
        return None

    return conn


def set_delta_status_and_output(projectid, delta_id, status, output=''):
    """Set the deltafile status and output into the database record """

    conn = get_django_db_connection(True)
    if not conn:
        conn = get_django_db_connection(False)

    cur = conn.cursor()
    cur.execute("UPDATE core_delta SET status = %s, updated_at = now(), output = %s WHERE id = %s AND project_id = %s",
                (status, output, delta_id, projectid))
    conn.commit()

    cur.close()
    conn.close()


def create_deltafile_with_pending_deltas(projectid, tempdir):
    """Retrieve the pending deltas from the db and create a deltafile-like
    json to be passed to the apply_deltas script"""

    conn = get_django_db_connection(is_test_db=True)
    if not conn:
        conn = get_django_db_connection(is_test_db=False)

    cur = conn.cursor()
    cur.execute("SELECT id, deltafile_id, content FROM core_delta WHERE project_id = %s AND status = %s;",
                (projectid, STATUS_PENDING))

    json_content = {
        "deltas": [],
        "files": [],
        "id": str(uuid.uuid4()),
        "project": projectid,
        "version": "1.0"
    }

    deltas = cur.fetchall()
    cur.close()
    conn.close()

    for delta in deltas:
        json_content["deltas"].append(delta[2])
        set_delta_status_and_output(projectid, delta[0], STATUS_BUSY)

    deltafile = os.path.join(tempdir, 'deltafile.json')
    with open(deltafile, 'w') as f:
        json.dump(json_content, f)

    return deltafile


def apply_deltas(projectid, project_file):
    """Start a QGIS docker container to apply a deltafile unsing the
    apply-delta script"""

    tempdir = tempfile.mkdtemp()
    create_deltafile_with_pending_deltas(projectid, tempdir)

    volumes = {
        tempdir: {'bind': '/io/', 'mode': 'rw'}
    }
    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        environment=load_env_file(),
        auto_remove=True,
        volumes=volumes)

    container.start()
    container.attach(logs=True)
    container_command = 'xvfb-run python3 entrypoint.py apply-delta {} {}'.format(
        projectid, project_file)

    exit_code, output = container.exec_run(container_command)
    container.kill()

    deltalog_file = os.path.join(tempdir, 'deltalog.json')
    with open(deltalog_file, 'r') as f:
        deltalog = json.load(f)

        for log in deltalog:
            delta_id = log['delta_id']
            status = log['status']
            if status == 'status_applied':
                status = STATUS_APPLIED
            elif status == 'status_conflict':
                status = STATUS_APPLIED_WITH_CONFLICTS
            elif status == 'status_apply_failed':
                status = STATUS_NOT_APPLIED
            else:
                status = STATUS_ERROR
            msg = log['msg']

            set_delta_status_and_output(projectid, delta_id, status, msg)

    logging.info(
        'apply_delta, projectid: {}, project_file: {}, exit_code: {}, output:\n\n{}'.format(
            projectid, project_file, exit_code, output.decode('utf-8')))

    # if exit_code not in [0, 1]:
    #     raise ApplyDeltaScriptException(output)
    return exit_code, output.decode('utf-8')


def check_status():
    """Launch a container to check that everything is working
    correctly."""

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        environment=load_env_file(),
        auto_remove=True)

    container.start()
    container.attach(logs=True)

    # TODO: create a command to actually start qgis and check some features
    container_command = 'echo QGIS container is running'

    exit_code, output = container.exec_run(container_command)
    container.kill()

    logging.info(
        'check_status, exit_code: {}, output:\n\n{}'.format(
            exit_code, output.decode('utf-8')))

    if not exit_code == 0:
        raise QgisException(output)
    return exit_code, output.decode('utf-8')
