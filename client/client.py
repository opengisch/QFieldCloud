#!/usr/bin/python3

import os
import json
import requests
import click

from glob import glob
from pathlib import Path

BASE_URL = 'http://dev.qfield.cloud/api/v1/'
# BASE_URL = 'http://localhost:8000/api/v1/'


@click.group()
def cli():
    pass


@cli.command()
@click.argument('username')
@click.argument('password')
def register_user(username, password):
    """Register new user and return the token"""

    url = BASE_URL + 'auth/registration/'
    data = {
        "username": username,
        "password1": password,
        "password2": password,
    }

    response = requests.post(
        url,
        data=data,
    )

    try:
        response.raise_for_status()
        print("User created")
        print('Your token is: {}'.format(response.json()['token']))
        print('Please store your token in the QFIELDCLOUD_TOKEN environment variable with:')
        print('export QFIELDCLOUD_TOKEN="{}"'.format(response.json()['token']))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('username')
@click.argument('password')
def login(username, password):
    """Login to QFieldCloud and print the token"""

    url = BASE_URL + 'auth/login/'
    data = {
        "username": username,
        "password": password,
    }

    response = requests.post(
        url,
        data=data,
    )

    try:
        response.raise_for_status()
        print('Your token is: {}'.format(response.json()['token']))
        print('Please store your token in the QFIELDCLOUD_TOKEN environment variable with:')
        print('export QFIELDCLOUD_TOKEN="{}"'.format(response.json()['token']))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('name')
@click.argument('owner')
@click.argument('description')
@click.option('--private/--public', default=True, help="Make the project private or public")
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def create_project(token, name, owner, description, private=True):
    """Create a new QFieldCloud project"""

    url = BASE_URL + 'projects/' + owner + '/'
    data = {
        "name": name,
        "description": description,
        "private": private
    }

    headers = {'Authorization': 'token {}'.format(token)}

    response = requests.post(
        url,
        data=data,
        headers=headers,
    )

    try:
        response.raise_for_status()
        print('Project created with id:')
        print(response.json()['id'])
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
@click.option('--include-public/--no-public', default=False)
def projects(token, include_public):
    """List QFieldCloud projects"""

    url = BASE_URL + 'projects/'
    headers = {'Authorization': 'token {}'.format(token)}
    params = {'include-public': include_public}

    response = requests.get(
        url,
        headers=headers,
        params=params,
    )

    try:
        response.raise_for_status()
        print(json.dumps(response.json(), indent=4, sort_keys=True))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('project_id')
@click.argument('local_file', type=click.File('rb'))
@click.argument('remote_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def push_file(token, project_id, local_file, remote_file):
    """Push file"""

    url = BASE_URL + 'files/' + project_id + '/' + remote_file + '/'
    headers = {
        'Authorization': 'token {}'.format(token),
    }
    files = {'file': local_file}
    response = requests.post(
        url,
        headers=headers,
        files=files,
    )
    try:
        response.raise_for_status()
        print("File uploaded")
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)



@cli.command()
@click.argument('project_id')
@click.argument('local_dir', type=click.Path(exists=True, file_okay=False))
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
@click.option('--filter-glob', default='*', help="Filter files glob")
@click.option('--recursive/--no-recursive', default=True, help="Recursively upload files")
def push_files(token, project_id, local_dir, filter_glob, recursive):
    """Push files"""

    middle = '**' if recursive else ''
    file_names = glob(os.path.join(local_dir, middle, filter_glob), recursive=recursive)
    # upload the QGIS project file at the end
    file_names.sort(key=lambda s: Path(s).suffix in ('.qgs', '.qgz') )

    for file_name in file_names:
        local_path = Path(file_name)

        if not local_path.is_file():
            continue

        remote_path = local_path.relative_to(local_dir)
        url = BASE_URL + 'files/' + project_id + '/' + str(remote_path) + '/'
        headers = {
            'Authorization': 'token {}'.format(token),
        }

        with open(local_path, 'rb')  as local_file:
            files = {'file': local_file}

            response = requests.post(
                url,  
                headers=headers,
                files=files,
            )

            try:
                response.raise_for_status()
                print("File \"{}\" uploaded".format(remote_path))
            except requests.HTTPError:
                print("Error uploading \"{}\": {}".format(remote_path, response))
                print(response.text)


@cli.command()
@click.argument('project_id')
@click.argument('remote_file')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def delete_file(token, project_id, remote_file):
    """Delete file"""

    url = BASE_URL + 'files/' + project_id + '/' + remote_file + '/'
    headers = {
        'Authorization': 'token {}'.format(token),
    }
    files = {'file': remote_file}
    response = requests.delete(
        url,
        headers=headers,
        files=files,
    )
    try:
        response.raise_for_status()
        print("File deleted")
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('project_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def list_files(token, project_id):
    """List files"""

    url = BASE_URL + 'files/' + project_id + '/'
    headers = {'Authorization': 'token {}'.format(token)}

    response = requests.get(
        url,
        headers=headers,
    )

    try:
        response.raise_for_status()
        print(json.dumps(response.json(), indent=4, sort_keys=True))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('project_id')
@click.argument('remote_file')
@click.argument('local_file')
@click.option('-v', '--version', 'version')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def pull_file(token, project_id, remote_file, local_file, version=None):
    """Pull file"""

    url = BASE_URL + 'files/' + project_id + '/' + remote_file + '/'
    headers = {'Authorization': 'token {}'.format(token)}
    params = {}
    if version:
        params = {'version': version}

    with requests.get(url, headers=headers, params=params, stream=True) as response:
        try:
            response.raise_for_status()
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
            print("File downloaded")
        except requests.HTTPError:
            print("Error: {}".format(response))
            print(response.text)


@cli.command()
@click.argument('deltafile_id')
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def delta_status(token, deltafile_id):
    """Delta status"""

    url = BASE_URL + 'delta-status/' + deltafile_id + '/'
    headers = {'Authorization': 'token {}'.format(token)}

    response = requests.get(
        url,
        headers=headers,
    )

    try:
        response.raise_for_status()
        print(json.dumps(response.json(), indent=4, sort_keys=True))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


@cli.command()
@click.argument('token', envvar='QFIELDCLOUD_TOKEN', type=str)
def logout(token):
    """Logout and delete the token"""

    url = BASE_URL + 'auth/logout/'
    headers = {'Authorization': 'token {}'.format(token)}

    response = requests.post(
        url,
        headers=headers,
    )

    try:
        response.raise_for_status()
        print(json.dumps(response.json(), indent=4, sort_keys=True))
    except requests.HTTPError:
        print("Error: {}".format(response))
        print(response.text)


if __name__ == '__main__':
    cli()
