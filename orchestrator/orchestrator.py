import os
import docker
import logging
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(
    filename='orchestrator.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s'
)

@app.route("/")
def status():
    return "Running!"


@app.route("/export-project/")
def export_project():
    app.logger.info('Processing /export-project/')
    project_dir = request.args.get('project-dir', default='', type=str)
    project_file = request.args.get('project-file', default='', type=str)

    output_dir = os.path.join(host_path(project_dir), 'export')
    project_dir = os.path.join(host_path(project_dir), 'real_files')

    volumes = {
        project_dir: {'bind': '/io/project', 'mode': 'ro'},
        output_dir: {'bind': '/io/output', 'mode': 'rw'},
    }

    app.logger.debug(
        'Mounted volumes: project_dir: {}, output_dir: {}'.format(
            project_dir, output_dir))

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
    app.logger.debug('Container command: {}'.format(container_command))

    container.stop()
    app.logger.debug(
        'Results from QGIS container: exit_code: {}, output: {}'.format(
            exit_code, output))

    response = jsonify(
        {'output': output.decode('utf-8'),
         'exit_code': exit_code}
    )

    if not exit_code == 0:
        response.status_code = 500
    return response


@app.route("/apply-delta/")
def apply_delta():
    app.logger.info('Processing /apply-delta/')
    project_dir = request.args.get('project-dir', default='', type=str)
    project_file = request.args.get('project-file', default='', type=str)
    delta_file = request.args.get('delta-file', default='', type=str)

    delta_dir = os.path.join(host_path(project_dir), 'deltas')
    project_dir = os.path.join(host_path(project_dir), 'real_files')

    volumes = {
        project_dir: {'bind': '/io/project', 'mode': 'rw'},
        delta_dir: {'bind': '/io/deltas', 'mode': 'rw'},
    }

    app.logger.debug(
        'Mounted volumes: project_dir: {}, delta_dir: {}'.format(
            project_dir, delta_dir))

    client = docker.from_env()
    container = client.containers.create(
        'qfieldcloud_qgis',
        volumes=volumes,
        auto_remove=True)

    container.start()
    container.attach(logs=True)
    container_command = './entrypoint.sh apply-delta delta apply /io/project/{} /io/deltas/{}'.format(
            project_file, delta_file)
    app.logger.debug('Container command: {}'.format(container_command))

    exit_code, output = container.exec_run(container_command)

    response = jsonify(
        {'output': output.decode('utf-8'),
         'exit_code': exit_code}
    )

    container.stop()

    app.logger.debug(
        'Results from QGIS container: exit_code: {}, output: {}'.format(
            exit_code, output))

    if not exit_code == 0:
        response.status_code = 500

    return response


def host_path(project):
    """Convert web-app docker path into host path"""

    basepath = Path(os.path.dirname(os.path.abspath(__file__)))
    basepath = str(basepath.parent)

    return os.path.join(basepath, 'user_projects_files', project)


if __name__ == "__main__":

    # TODO: set debug false and correct host settings
    app.run(debug=True, host='0.0.0.0')
