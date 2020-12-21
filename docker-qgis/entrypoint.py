#!/usr/bin/env python3

import argparse
import os
import tempfile
import hashlib
import logging
import json

from pathlib import PurePath, Path

import boto3

from qgis.core import (
    QgsProject, QgsOfflineEditing, QgsVectorLayer, QgsMapSettings)
from qgis.testing import start_app, mocked

from qfieldsync.core.offline_converter import OfflineConverter

import apply_deltas

# Get environment variables
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL")


def _get_s3_resource():
    """Get S3 Service Resource object"""
    # Create AWS session
    session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION_NAME
    )

    return session.resource('s3', endpoint_url=AWS_S3_ENDPOINT_URL)


def _get_s3_bucket():
    """Get S3 Bucket according to the env variable
    AWS_STORAGE_BUCKET_NAME"""

    s3 = _get_s3_resource()
    bucket = s3.Bucket(AWS_STORAGE_BUCKET_NAME)
    return bucket


def _get_sha256sum(filepath):
    """Calculate sha256sum of a file"""
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    with filepath as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()


def _download_project_directory(projectid):
    """Download the files in the project "working" directory from the S3
    Storage into a temporary directory. Returns the directory path"""

    bucket = _get_s3_bucket()

    # Prefix of the working directory on the Storages
    working_prefix = '/'.join(['projects', projectid, 'files'])

    # Create a temporary directory
    tmpdir = tempfile.mkdtemp()

    # Create a local working directory
    working_dir = os.path.join(tmpdir, 'files')
    os.mkdir(working_dir)

    # Download the files
    for obj in bucket.objects.filter(Prefix=working_prefix):
        path = PurePath(obj.key)

        # Get the path of the file relative to the project directory
        filepath = path.relative_to(*path.parts[:2])

        dest_filepath = os.path.join(tmpdir, filepath)
        os.makedirs(Path(dest_filepath).parent, exist_ok=True)
        bucket.download_file(obj.key, dest_filepath)

    return tmpdir


def _upload_project_directory(projectid, local_dir):
    """Upload the files in the local_dir (export directory) to the
    storage"""

    bucket = _get_s3_bucket()

    export_prefix = '/'.join(['projects', projectid, 'export'])

    # Remove existing export directory on the storage
    bucket.objects.filter(Prefix=export_prefix).delete()

    # Loop recursively in the local export directory
    for elem in Path(local_dir).rglob('*.*'):
        # Don't upload .qgs~ and .qgz~ files
        if str(elem).endswith('~'):
            continue
        # Calculate sha256sum
        with open(elem, 'rb') as e:
            sha256sum = _get_sha256sum(e)

        # Create the key
        key = '/'.join([export_prefix, str(elem.relative_to(*elem.parts[:4]))])
        metadata = {'sha256sum': sha256sum}
        bucket.upload_file(str(elem), key, ExtraArgs={"Metadata": metadata})


def _upload_delta_modified_files(projectid, local_dir):
    """Upload the files changed by apply delta to the files/ directory of
    the storage, qgs project excluded"""

    bucket = _get_s3_bucket()

    files_prefix = '/'.join(['projects', projectid, 'files'])

    # Loop recursively in the local files directory
    for elem in Path(local_dir).rglob('*.*'):
        # Don't upload .qgs~ and .qgz~ files
        if str(elem).endswith('~'):
            continue
        if str(elem).endswith('qfieldcloudbackup'):
            continue

        # Calculate sha256sum
        with open(elem, 'rb') as e:
            sha256sum = _get_sha256sum(e)

        # Create the key
        key = '/'.join([files_prefix, str(elem.relative_to(*elem.parts[:4]))])
        metadata = {'sha256sum': sha256sum}

        # Check if the file is different on the storage
        if not bucket.Object(key).metadata.get('Sha256sum', None) == sha256sum:
            bucket.upload_file(
                str(elem), key, ExtraArgs={"Metadata": metadata})


def _call_qfieldsync_exporter(project_filepath, export_dir):
    """Call the function of QFieldSync to export a project for QField"""
    start_app()

    # Set the canvas object name to the
    # exported project because qfieldsync running
    # headless on the server doesn't do that
    iface = mocked.get_iface()
    canvas = iface.mapCanvas()
    canvas.setObjectName("theMapCanvas")

    project = QgsProject.instance()
    if not os.path.exists(project_filepath):
        raise FileNotFoundError(project_filepath)

    if not project.read(project_filepath):
        raise Exception(
            "Unable to open file with QGIS: {}".format(project_filepath))

    # Set the crs from the original project to the canvas
    # so it will be present in the exported project
    canvas.setDestinationCrs(project.crs())

    layers = project.mapLayers()
    # Check if the layers are valid (i.e. if the datasources are available)
    layers_check = {}
    for layer in layers.values():
        layers_check[layer.id()] = {
            'name': layer.name(),
            'valid': layer.dataProvider().isValid()
        }

    with open('/io/exportlog.json', 'w') as f:
        f.write(json.dumps(layers_check))

    # Calculate the project extent
    mapsettings = QgsMapSettings()

    # TODO: Check if the extent have been defined in QFieldSync
    # TODO: Do I need to really exclude all the non-vector layers
    # from the extent?

    # Only vector layers
    mapsettings.setLayers(
        [layers[key] for key in layers if type(layers[key]) == QgsVectorLayer]
    )

    extent = mapsettings.fullExtent()

    offline_editing = QgsOfflineEditing()
    offline_converter = OfflineConverter(
        project, export_dir, extent, offline_editing)

    # Disable the basemap generation because it needs the processing
    # plugin to be installed
    offline_converter.project_configuration.create_base_map = False
    offline_converter.convert()


def _export_project(args):
    projectid = args.projectid
    project_file = args.project_file

    tmpdir = _download_project_directory(projectid)

    project_filepath = os.path.join(
        tmpdir, 'files', project_file)

    # create an export directory inside the tempdir
    export_dir = os.path.join(tmpdir, 'export')
    os.mkdir(export_dir)

    _call_qfieldsync_exporter(project_filepath, export_dir)

    # Upload changed data files to the "export" directory on the storage
    _upload_project_directory(projectid, export_dir)


def _apply_delta(args):
    projectid = args.projectid
    project_file = args.project_file

    tmpdir = _download_project_directory(projectid)
    deltafile = '/io/deltafile.json'

    project_filepath = os.path.join(
        tmpdir, 'files', project_file)

    has_errors = apply_deltas.cmd_delta_apply(
        opts={'project': project_filepath,
              'delta_file': deltafile,
              'delta_log': '/io/deltalog.json',
              'inverse': False,
              'overwrite_conflicts': args.overwrite_conflicts,
              'transaction': False})

    _upload_delta_modified_files(
        projectid, os.path.join(tmpdir, 'files'))

    exit(int(has_errors))


if __name__ == '__main__':

    # Set S3 logging levels
    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('nose').setLevel(logging.CRITICAL)
    logging.getLogger('s3transfer').setLevel(logging.CRITICAL)
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)

    parser = argparse.ArgumentParser(prog='COMMAND')

    subparsers = parser.add_subparsers(dest='cmd')

    parser_export = subparsers.add_parser('export', help='Export a project')
    parser_export.add_argument('projectid', type=str, help='projectid')
    parser_export.add_argument(
        'project_file', type=str, help='QGIS project file path')
    parser_export.set_defaults(func=_export_project)

    parser_delta = subparsers.add_parser(
        'apply-delta', help='Apply deltafile')
    parser_delta.add_argument('projectid', type=str, help='projectid')
    parser_delta.add_argument(
        'project_file', type=str, help='QGIS project file path')
    parser_delta.add_argument(
        '--overwrite-conflicts',
        dest='overwrite_conflicts',
        action='store_true')
    parser_delta.add_argument(
        '--no-overwrite-conflicts',
        dest='overwrite_conflicts',
        action='store_false')
    parser_delta.set_defaults(
        func=_apply_delta,
        overwrite_conflicts=True)

    args = parser.parse_args()
    args.func(args)
