import os
from pathlib import Path

import docker


def load_env_file():
    """Read env file and return a dict with the variables"""

    environment = {}
    with open('../conf/.env.app') as f:
        for line in f:
            splitted = line.rstrip().split('=')
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
    container.stop()

    # TODO: communicate to Django that the work is done...
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
    container.stop()

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

    # TODO: create an actual command to start qgis and check some features
    # container_command = 'xvfb-run python3 entrypoint.py apply-delta {} {} {}'.format(
    #     projectid, project_file, delta_file)
    container_command = 'echo QGIS container is running'

    exit_code, output = container.exec_run(container_command)
    container.stop()

    return exit_code, output.decode('utf-8')
