#!/usr/bin/env python3

import argparse
import os
import tempfile
import hashlib
import logging

from pathlib import PurePath, Path

import boto3

from qgis.core import (
    QgsProject, QgsOfflineEditing, QgsVectorLayer, QgsMapSettings)
from qgis.testing import start_app

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


def _download_delta_file(projectid, delta_file):
    """Download a delta file from the storage"""

    bucket = _get_s3_bucket()

    # Prefix of the working directory on the Storages
    deltafile_key = '/'.join(['projects', projectid, 'deltas', delta_file])

    bucket.download_file(deltafile_key, '/tmp/deltafile.json')
    return '/tmp/deltafile.json'


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

    project = QgsProject.instance()
    if not os.path.exists(project_filepath):
        raise FileNotFoundError(project_filepath)

    if not project.read(project_filepath):
        raise Exception(
            "Unable to open file with QGIS: {}".format(project_filepath))

    # Calculate the project extent
    project = QgsProject.instance()
    layers = project.mapLayers()
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


def _store_deltafile_status(projectid, delta_file, status):
    """Update the "status" metadata of the deltafile on the storage"""
    s3 = _get_s3_resource()
    deltafile_key = '/'.join(['projects', projectid, 'deltas', delta_file])
    obj = s3.Object(AWS_STORAGE_BUCKET_NAME, deltafile_key)

    obj.metadata.update({'status': status})
    obj.copy_from(
        CopySource={'Bucket': AWS_STORAGE_BUCKET_NAME, 'Key': deltafile_key},
        Metadata=obj.metadata, MetadataDirective='REPLACE')


def _apply_delta(args):
    projectid = args.projectid
    project_file = args.project_file
    deltafile_name = args.delta_file

    tmpdir = _download_project_directory(projectid)
    deltafile = _download_delta_file(projectid, deltafile_name)

    project_filepath = os.path.join(
        tmpdir, 'files', project_file)

    return_code = apply_deltas.cmd_delta_apply(
        opts={'project': project_filepath,
              'delta_file': deltafile,
              'inverse': False})

    _upload_delta_modified_files(
        projectid, os.path.join(tmpdir, 'files'))

    if return_code == 0:
        status = 'STATUS_APPLIED'
    elif return_code == 1:
        status = 'STATUS_APPLIED_WITH_CONFLICTS'
    else:
        status = 'STATUS_NOT_APPLIED'

    _store_deltafile_status(projectid, deltafile_name, status)
    exit(return_code)


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
    parser_delta.add_argument('delta_file', type=str, help='Delta file path')
    parser_delta.set_defaults(func=_apply_delta)

    args = parser.parse_args()
    args.func(args)
