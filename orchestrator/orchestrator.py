import os
import logging
from pathlib import Path

import docker


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


def apply_delta(projectid, project_file, delta_file):
    """Start a QGIS docker container to apply a deltafile unsing the
    apply-delta script"""

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        environment=load_env_file(),
        auto_remove=True)

    container.start()
    container.attach(logs=True)
    container_command = 'xvfb-run python3 entrypoint.py apply-delta {} {} {}'.format(
        projectid, project_file, delta_file)

    exit_code, output = container.exec_run(container_command)
    container.kill()

    logging.info(
        'export_project, projectid: {}, project_file: {}, delta_file: {}, exit_code: {}, output:\n\n{}'.format(
            projectid, project_file, delta_file, exit_code, output.decode('utf-8')))

    if exit_code not in [0, 1]:
        raise ApplyDeltaScriptException(output)
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
