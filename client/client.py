#!/usr/bin/python3

from typing import Any, Dict
import os
import json
from time import sleep
import requests
import click

from glob import glob
from pathlib import Path

# BASE_URL = 'https://dev.qfield.cloud/api/v1/'
# BASE_URL = 'https://app.qfield.cloud/api/v1/'
BASE_URL = 'http://localhost:8000/api/v1/'


@click.group()
def cli():
    pass


@cli.command()
@click.argument('username')
@click.argument('password')
@click.argument('email')
def register_user(username, password, email):
    """Register a new user and return the token"""

    resp = cloud_request('POST', 'auth/registration', data={
        'username': username,
        'password1': password,
        'password2': password,
        'email': email,
    })
    payload = resp.json()

    print('User created')
    print(payload)
    print(f'\nYour token is: {payload["token"]}')
    print('Please store your token in the QFIELDCLOUD_TOKEN environment variable with:')
    print(f'export QFIELDCLOUD_TOKEN="{payload["token"]}"')


@cli.command()
@click.argument('username')
@click.argument('password')
def login(username, password):
    """Login to QFieldCloud and print the token"""

    resp = cloud_request('POST', 'auth/login', data={
        'username': username,
        'password': password,
    })
    payload = resp.json()

    print(f'Your token is: {payload["token"]}')
    print('Please store your token in the QFIELDCLOUD_TOKEN environment variable with:')
    print(f'export QFIELDCLOUD_TOKEN="{payload["token"]}"')


@cli.command()
@click.argument('name')
@click.argument('owner')
@click.argument('description')
@click.option('--private/--public', default=True, help='Make the project private or public')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def create_project(token, name, owner, description, private=True):
    """Create a new QFieldCloud project"""

    resp = cloud_request('POST', 'projects', token=token, data={
        'name': name,
        'owner': owner,
        'description': description,
        'private': private,
    })
    payload = resp.json()

    print(f'Project created with id: {payload["id"]}')


@cli.command()
@click.argument('project_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def delete_project(token, project_id):
    """Delete an existing QFieldCloud project"""

    _ = cloud_request('DELETE', f'projects/{project_id}', token=token)

    print(f'Project successfully deleted with id: {project_id}')


@cli.command()
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
@click.option('--include-public/--no-public', default=False)
def projects(token, include_public):
    """List QFieldCloud projects"""

    resp = cloud_request('GET', 'projects', token=token, params={
        'include-public': include_public,
    })
    payload = resp.json()

    print('Available projects:')
    print(json.dumps(payload, indent=2, sort_keys=True))


@cli.command()
@click.argument('project_id')
@click.argument('local_file', type=click.File('rb'))
@click.argument('remote_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def upload_file(token, project_id, local_file, remote_file):
    """Upload file"""

    _ = cloud_request('POST', f'files/{project_id}/{remote_file}', token=token, files={
        'file': local_file,
    })

    print(f'File uploaded "{remote_file}"')


@cli.command()
@click.argument('project_id')
@click.argument('local_dir', type=click.Path(exists=True, file_okay=False))
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
@click.option('--filter-glob', default='*', help='Filter files glob')
@click.option('--recursive/--no-recursive', default=True, help='Recursively upload files')
def upload_files(token, project_id, local_dir, filter_glob, recursive):
    """Upload files"""

    middle = '**' if recursive else ''
    file_names = glob(os.path.join(local_dir, middle, filter_glob), recursive=recursive)
    # upload the QGIS project file at the end
    file_names.sort(key=lambda s: Path(s).suffix in ('.qgs', '.qgz'))

    for file_name in file_names:
        local_path = Path(file_name)

        if not local_path.is_file():
            continue

        remote_path = local_path.relative_to(local_dir)

        with open(file_name, 'rb') as local_file:
            _ = cloud_request('POST', f'files/{project_id}/{remote_path}', token=token, files={
                'file': local_file,
            })

            print(f'File "{remote_path}" uploaded')


@cli.command()
@click.argument('project_id')
@click.argument('remote_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def delete_file(token, project_id, remote_file):
    """Delete an existing QFieldCloud project file"""

    _ = cloud_request('DELETE', f'files/{project_id}/{remote_file}', token=token)

    print(f'Project file successfully deleted with id: {remote_file}')


@cli.command()
@click.argument('project_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def files(token, project_id):
    """List project files"""

    resp = cloud_request('GET', f'files/{project_id}', token=token)
    payload = resp.json()

    print(f'Project files for project {project_id}:')
    print(json.dumps(payload, indent=2, sort_keys=True))


@cli.command()
@click.argument('project_id')
@click.argument('remote_file')
@click.argument('local_file')
@click.option('-v', '--version', 'version')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def download_file(token, project_id, remote_file, local_file, version=None):
    """Pull file"""
    params = {}

    if version:
        params = {'version': version}

    resp = cloud_request('GET', f'files/{project_id}/{remote_file}', token=token, stream=True, params=params)

    with open(local_file, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)
    print(f'File downloaded at "{local_file}"')


@cli.command()
@click.argument('project_id')
@click.argument('local_dir')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def download_files(token, project_id, local_dir):
    """Pull file"""

    resp = cloud_request('GET', f'files/{project_id}', token=token)
    files = resp.json()
    files_count = 0

    for file in files:
        local_file = Path(f'{local_dir}/{file["name"]}')
        resp = cloud_request('GET', f'files/{project_id}/{file["name"]}', token=token, stream=True, exit_on_error=False)

        if not resp.ok:
            print(f'{resp.request.method} {resp.url} got HTTP {resp.status_code}')
            continue

        if not local_file.parent.exists():
            local_file.parent.mkdir(parents=True)

        with open(local_file, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
        files_count += 1
        print(f'File downloaded at "{local_file}"')

    print(f'Done! Downloaded {files_count}/{len(files)} files.')


@cli.command()
@click.argument('project_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def export_files(token, project_id):
    """Initiate a file export for qfield"""

    resp = cloud_request('POST', f'qfield-files/export/{project_id}', token=token)
    payload = resp.json()

    print('File export started:')
    print(json.dumps(payload, indent=2, sort_keys=True))


@cli.command()
@click.argument('project_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def export_files_status(token, project_id):
    """Check exported files status"""

    resp = cloud_request('GET', f'qfield-files/export/{project_id}', token=token)
    payload = resp.json()

    print('File export status:')
    print(json.dumps(payload, indent=2, sort_keys=True))


@cli.command()
@click.argument('project_id')
@click.argument('remote_file')
@click.argument('local_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def export_files_download(token, project_id, remote_file, local_file):
    """Download exported file"""

    resp = cloud_request('GET', f'qfield-files/{project_id}/{remote_file}', token=token, stream=True)

    with open(local_file, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)

    print(f'File downloaded at "{local_file}"')


@cli.command()
@click.argument('project_id')
@click.argument('local_dir')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
@click.option('--accept-old-export/--force-fresh-export', default=True, help='Accept old exports too')
def export(token, project_id, local_dir, accept_old_export):
    """Export and downloads files for qfield"""

    _ = cloud_request('POST', f'qfield-files/export/{project_id}', token=token)

    while True:
        resp = cloud_request('GET', f'qfield-files/export/{project_id}', token=token, exit_on_error=False)

        if not resp.ok:
            print(f'{resp.request.method} {resp.url} got HTTP {resp.status_code}')
            sleep(1)
            continue

        payload = resp.json()
        status = payload['status']
        print(f'Status updated: {status}')

        if status == 'STATUS_EXPORTED':
            break

        if status == 'STATUS_ERROR':
            if accept_old_export:
                break
            else:
                return

    resp = cloud_request('GET', f'qfield-files/{project_id}', token=token)
    payload = resp.json()
    files = payload['files']

    for file in files:
        resp = cloud_request('GET', f'qfield-files/{project_id}/{file["name"]}', token=token, stream=True)
        local_file = Path(local_dir + '/' + file['name'])
        local_file.parent.mkdir(parents=True, exist_ok=True)

        with open(local_file, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        print(f'File downloaded {local_file}')

    print('Done!')


@cli.command()
@click.argument('project_id')
@click.argument('deltafile_id', required=False)
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def delta_status(token, project_id, deltafile_id=None):
    """Delta status"""

    if deltafile_id is None:
        url = f'deltas/{project_id}'
    else:
        url = f'deltas/{project_id}/{deltafile_id}'

    resp = cloud_request('GET', url, token=token)
    payload = resp.json()

    print(json.dumps(payload, indent=2, sort_keys=True))


@cli.command()
@click.argument('project_id')
@click.argument('delta_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def upload_deltafile(token, project_id, delta_file):
    """Uploads deltafile and checks for the status until final status reached"""
    deltas = None

    with open(delta_file, 'r') as f:
        try:
            deltas = json.load(f)
        except Exception as error:
            print('Failed to read deltafile as json')
            print(error)

    assert deltas

    # Upload deltafile
    with open(delta_file, 'rb') as local_file:
        _ = cloud_request('GET', f'deltas/{project_id}', token=token, files={
            'file': local_file
        })

        print(f'Deltafile "{delta_file}" uploaded')

    # Trigger deltafile apply
    _ = cloud_request('POST', f'deltas/{project_id}', token=token)
    print('Deltafile application triggered')

    while True:
        resp = cloud_request('GET', f'deltas/{project_id}/{deltas["id"]}', token=token, exit_on_error=False)

        if not resp.ok:
            print(f'{resp.request.method} {resp.url} got HTTP {resp.status_code}')
            sleep(1)
            continue

        payload = resp.json()
        statuses = set()
        for delta in payload:
            statuses.add(delta['status'].upper())

        print(f'Delta statuses: {statuses}')

        if statuses.issubset({'STATUS_APPLIED', 'STATUS_CONFLICT', 'STATUS_ERROR'}):
            return


@cli.command()
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def logout(token):
    """Logout and delete the token"""

    resp = cloud_request('POST', 'auth/logout', token=token)
    payload = resp.json()

    print(json.dumps(payload, indent=2, sort_keys=True))


def cloud_request(
        method: str,
        path: str,
        data: Any = None,
        params: Dict[str, str] = {},
        headers: Dict[str, str] = {},
        files: Dict[str, str] = None,
        stream: bool = False,
        exit_on_error: bool = True,
        token: str = None) -> requests.Response:
    headers_copy = {**headers}
    if token:
        headers_copy['Authorization'] = f'token {token}'

    if path.startswith('/'):
        path = path[1:]

    if not path.endswith('/'):
        path += '/'

    response = requests.request(
        method=method,
        url=BASE_URL + path,
        data=data,
        params=params,
        headers=headers_copy,
        files=files,
        stream=stream,
        # redirects from POST requests automagically turn into GET requests, so better forbid redirects
        allow_redirects=False,
    )

    try:
        response.raise_for_status()

        return response
    except requests.HTTPError:
        if exit_on_error:
            is_error_printed = 1
            print(f'{response.request.method} {response.url} got HTTP {response.status_code}')

            if response.headers.get('Content-Type') == 'application/json':
                try:
                    payload = response.json()
                    print(json.dumps(payload, sort_keys=True, indent=2))
                    is_error_printed = True
                except Exception:
                    pass

            if is_error_printed:
                exit(1)
            else:
                print('Failed to read error response as json, the contained text is:')
                print(response.text)
                exit(2)
        else:
            return response


if __name__ == '__main__':
    cli()
