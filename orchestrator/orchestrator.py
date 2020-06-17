import os
import docker
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/")
def status():
    return "Running!"


@app.route("/export-project/")
def export_project():
    project_dir = request.args.get('project-dir', default='', type=str)
    project_file = request.args.get('project-file', default='', type=str)

    output_dir = os.path.join(host_path(project_dir), 'export')
    project_dir = os.path.join(host_path(project_dir), 'real_files')

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
    exit_code, output = container.exec_run(
        './entrypoint.sh export /io/project/{} /io/output/'.format(
            project_file))

    print(output)
    container.stop()

    if not exit_code == 0:
        response = jsonify({'output': output})
        response.status_code = 500
        return response

    return "Eported to output directory: {}\n".format(output_dir)


@app.route("/apply-delta/")
def apply_delta():
    project_dir = request.args.get('project-dir', default='', type=str)
    project_file = request.args.get('project-file', default='', type=str)
    delta_file = request.args.get('delta-file', default='', type=str)

    delta_dir = os.path.join(host_path(project_dir), 'deltas')
    project_dir = os.path.join(host_path(project_dir), 'real_files')

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

    exit_code, output = container.exec_run(
        './entrypoint.sh apply-delta delta apply /io/project/{} /io/deltas/{}'.format(
            project_file, delta_file))

    response = jsonify(
        {'output': output,
         'exit_code': exit_code}
    )

    container.stop()

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
