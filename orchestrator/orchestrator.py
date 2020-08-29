import os
from pathlib import Path

import docker


def host_path(project):
    """Convert web-app docker path into host path"""

    basepath = Path(os.path.dirname(os.path.abspath(__file__)))
    basepath = str(basepath.parent)

    return os.path.join(basepath, 'user_projects_files', project)


def export_project(projectid, project_file):
    """Start a QGIS docker container to export the project using QFieldSync """
    output_dir = os.path.join(host_path(projectid), 'export')
    project_dir = os.path.join(host_path(projectid), 'real_files')

    volumes = {
        project_dir: {'bind': '/io/project', 'mode': 'ro'},
        output_dir: {'bind': '/io/output', 'mode': 'rw'},
    }

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        volumes=volumes,
        auto_remove=True)

    container.start()
    container.attach(logs=True)
    container_command = './entrypoint.sh export /io/project/{} /io/output/'.format(
        project_file)

    exit_code, output = container.exec_run(container_command)

    container.stop()

    return exit_code, output


def apply_delta(projectid, project_file, delta_file):
    """Start a QGIS docker container to apply a deltafile unsing the
    apply-delta script"""
    delta_dir = os.path.join(host_path(projectid), 'deltas')
    project_dir = os.path.join(host_path(projectid), 'real_files')

    volumes = {
        project_dir: {'bind': '/io/project', 'mode': 'rw'},
        delta_dir: {'bind': '/io/deltas', 'mode': 'rw'},
    }

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        volumes=volumes,
        auto_remove=True)

    container.start()
    container.attach(logs=True)
    container_command = './entrypoint.sh apply-delta delta apply /io/project/{} /io/deltas/{}'.format(
        project_file, delta_file)

    exit_code, output = container.exec_run(container_command)

    container.stop()

    return exit_code, output
