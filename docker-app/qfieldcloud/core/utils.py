import os
import django_rq
import hashlib
import boto3
from botocore.errorfactory import ClientError
import posixpath
from pathlib import PurePath

from django.core.files.uploadedfile import (
    InMemoryUploadedFile, TemporaryUploadedFile)
from django.conf import settings

from redis import Redis, exceptions


def export_project(projectid, project_file):
    """Call the orchestrator API to export a project with QFieldSync"""

    queue = django_rq.get_queue('export')
    job = queue.enqueue('orchestrator.export_project',
                        projectid=projectid,
                        project_file=str(project_file))

    return job


def apply_delta(projectid, project_file, delta_file, jobid):
    """Call the orchestrator API to apply a delta file"""

    queue = django_rq.get_queue('delta')
    job = queue.enqueue('orchestrator.apply_delta',
                        job_id=jobid,
                        projectid=projectid,
                        project_file=str(project_file),
                        delta_file=delta_file)

    return job


def check_orchestrator_status():
    """Call the orchestrator to check if he's able to launch a QGIS
    container"""

    queue = django_rq.get_queue('export')
    job = queue.enqueue('orchestrator.check_status')

    return job


def get_job(queue, jobid):
    """Get the job from the specified queue or None"""

    queue = django_rq.get_queue(queue)
    return queue.fetch_job(jobid)


def redis_is_running():
    try:
        connection = Redis(
            'redis',
            password=os.environ.get("REDIS_PASSWORD")
        )
        connection.set('foo', 'bar')
    except exceptions.ConnectionError:
        return False

    return True


def get_s3_session():
    """Get S3 session"""

    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME
    )
    return session


def get_s3_bucket():
    """Get S3 Bucket according to the env variable
    AWS_STORAGE_BUCKET_NAME"""

    session = get_s3_session()

    # Get the bucket objects
    s3 = session.resource('s3', endpoint_url=settings.AWS_S3_ENDPOINT_URL)
    return s3.Bucket(settings.AWS_STORAGE_BUCKET_NAME)


def get_s3_client():
    """Get S3 client"""

    s3_client = boto3.client(
        's3',
        region_name=settings.AWS_S3_REGION_NAME,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
    )
    return s3_client


def get_sha256(file):
    """Return the sha256 hash of the file"""
    if type(file) in [InMemoryUploadedFile, TemporaryUploadedFile]:
        return _get_sha256_memory_file(file)
    else:
        return _get_sha256_file(file)


def _get_sha256_memory_file(file):
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()

    for chunk in file.chunks(BLOCKSIZE):
        hasher.update(chunk)

    file.seek(0)
    return hasher.hexdigest()


def _get_sha256_file(file):
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    with file as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()


def safe_join(base, *paths):
    """
    A version of django.utils._os.safe_join for S3 paths.
    Joins one or more path components to the base path component
    intelligently. Returns a normalized version of the final path.
    The final path must be located inside of the base path component
    (otherwise a ValueError is raised).
    Paths outside the base path indicate a possible security
    sensitive operation.
    """
    base_path = base
    base_path = base_path.rstrip('/')
    paths = [p for p in paths]

    final_path = base_path + '/'
    for path in paths:
        _final_path = posixpath.normpath(posixpath.join(final_path, path))
        # posixpath.normpath() strips the trailing /. Add it back.
        if path.endswith('/') or _final_path + '/' == final_path:
            _final_path += '/'
        final_path = _final_path
    if final_path == base_path:
        final_path += '/'

    # Ensure final_path starts with base_path and that the next character after
    # the base path is /.
    base_path_len = len(base_path)
    if (not final_path.startswith(base_path) or final_path[base_path_len] != '/'):
        raise ValueError('the joined path is located outside of the base path'
                         ' component')

    return final_path.lstrip('/')


def get_qgis_project_file(projectid):
    """Return the relative path inside the project of the qgs/qgz file or
    None if no qgs/qgz file is present"""

    bucket = get_s3_bucket()

    prefix = 'projects/{}/files/'.format(projectid)

    for obj in bucket.objects.filter(Prefix=prefix):
        if obj.key.lower().endswith('.qgs') or obj.key.lower().endswith('.qgz'):
            path = PurePath(obj.key)
            return str(path.relative_to(*path.parts[:3]))

    return None


def check_s3_key(key):
    """Check to see if an object exists on S3. It it exists, the function
    returns the sha256 of the file from the metadata"""

    client = get_s3_client()
    try:
        head = client.head_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    except ClientError as e:
        if e.response['ResponseMetadata']['HTTPStatusCode'] == 404:
            return None
        else:
            raise e

    return head['Metadata']['Sha256sum']
