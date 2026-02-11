import hashlib
import io
import json
import logging
import os
from datetime import datetime
from pathlib import PurePath
from typing import IO, NamedTuple

import boto3
import jsonschema
import mypy_boto3_s3
from botocore.errorfactory import ClientError
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

from qfieldcloud.settings_utils import DjangoStorages

logger = logging.getLogger(__name__)


class S3PrefixPath(NamedTuple):
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    Key: str


class S3Object(NamedTuple):
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    name: str
    key: str
    last_modified: datetime
    size: int
    etag: str
    md5sum: str


class S3ObjectVersion:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    def __init__(
        self, name: str, data: mypy_boto3_s3.service_resource.ObjectVersion
    ) -> None:
        self.name = name
        self._data = data

    @property
    def id(self) -> str:
        """Returns the version id"""
        # NOTE id and version_id are the same thing
        return self._data.id

    @property
    def key(self) -> str:
        return self._data.key

    @property
    def last_modified(self) -> datetime:
        return self._data.last_modified

    @property
    def size(self) -> int:
        return self._data.size

    @property
    def e_tag(self) -> str:
        return self._data.e_tag

    @property
    def md5sum(self) -> str:
        return self._data.e_tag.replace('"', "")

    @property
    def is_latest(self) -> bool:
        return self._data.is_latest

    @property
    def display(self) -> str:
        return self.last_modified.strftime("v%Y%m%d%H%M%S")


class S3ObjectWithVersions(NamedTuple):
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    latest: S3ObjectVersion
    versions: list[S3ObjectVersion]

    @property
    def total_size(self) -> int:
        """Total size of all versions"""
        # latest is also in versions
        return sum(v.size for v in self.versions if v.size is not None)


def get_legacy_s3_credentials() -> DjangoStorages:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    assert settings.LEGACY_STORAGE_NAME

    return settings.STORAGES[settings.LEGACY_STORAGE_NAME]


def get_s3_session() -> boto3.Session:
    """Get a new S3 Session instance using Django settings

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    session = boto3.Session(
        aws_access_key_id=get_legacy_s3_credentials()["OPTIONS"]["access_key"],
        aws_secret_access_key=get_legacy_s3_credentials()["OPTIONS"]["secret_key"],
        region_name=get_legacy_s3_credentials()["OPTIONS"]["region_name"],
    )
    return session


def get_s3_bucket() -> mypy_boto3_s3.service_resource.Bucket:
    """
    Get a new S3 Bucket instance using Django settings.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    bucket_name = get_legacy_s3_credentials()["OPTIONS"]["bucket_name"]

    assert bucket_name, "Expected `bucket_name` to be non-empty string!"

    session = get_s3_session()
    s3 = session.resource(
        "s3",
        endpoint_url=get_legacy_s3_credentials()["OPTIONS"]["endpoint_url"],
    )

    # Ensure the bucket exists
    s3.meta.client.head_bucket(Bucket=bucket_name)

    # Get the bucket resource
    return s3.Bucket(bucket_name)


def get_s3_client() -> mypy_boto3_s3.Client:
    """Get a new S3 client instance using Django settings

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    s3_session = get_s3_session()
    s3_client = s3_session.client(
        "s3",
        endpoint_url=get_legacy_s3_credentials()["OPTIONS"]["endpoint_url"],
    )
    return s3_client


def _get_sha256_memory_file(file: InMemoryUploadedFile | TemporaryUploadedFile) -> str:
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()

    for chunk in file.chunks(BLOCKSIZE):
        hasher.update(chunk)

    file.seek(0)
    return hasher.hexdigest()


def _get_sha256_file(file: IO) -> str:
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    buf = file.read(BLOCKSIZE)

    while len(buf) > 0:
        hasher.update(buf)
        buf = file.read(BLOCKSIZE)

    file.seek(0)

    return hasher.hexdigest()


def _get_md5sum_memory_file(file: InMemoryUploadedFile | TemporaryUploadedFile) -> str:
    BLOCKSIZE = 65536
    hasher = hashlib.md5()

    for chunk in file.chunks(BLOCKSIZE):
        hasher.update(chunk)

    file.seek(0)
    return hasher.hexdigest()


def _get_md5sum_file(file: IO) -> str:
    BLOCKSIZE = 65536
    hasher = hashlib.md5()

    buf = file.read(BLOCKSIZE)

    while len(buf) > 0:
        hasher.update(buf)
        buf = file.read(BLOCKSIZE)

    file.seek(0)
    return hasher.hexdigest()


def strip_json_null_bytes(file: IO) -> IO:
    """Return JSON string stream without NULL chars."""
    result = io.BytesIO()
    result.write(file.read().decode().replace(r"\u0000", "").encode())
    file.seek(0)
    result.seek(0)

    return result


def is_the_qgis_file(filename: str) -> bool:
    """Returns whether the filename seems to be a QGIS project file by checking the file extension.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    path = PurePath(filename)

    if path.suffix.lower() in (".qgs", ".qgz"):
        return True

    return False


def get_qgis_project_file(project_id: str) -> str | None:
    """Return the relative path inside the project of the qgs/qgz file or
    None if no qgs/qgz file is present

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    bucket = get_s3_bucket()

    prefix = f"projects/{project_id}/files/"

    for obj in bucket.objects.filter(Prefix=prefix):
        if is_the_qgis_file(obj.key):
            path = PurePath(obj.key)
            return str(path.relative_to(*path.parts[:3]))

    return None


def check_s3_key(key: str) -> str | None:
    """Check to see if an object exists on S3. It it exists, the function
    returns the sha256 of the file from the metadata

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    client = get_s3_client()
    try:
        head = client.head_object(
            Bucket=get_legacy_s3_credentials()["OPTIONS"]["bucket_name"],
            Key=key,
        )
    except ClientError as e:
        if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return None
        else:
            raise e

    metadata = head["Metadata"]
    if "sha256sum" in metadata:
        return metadata["sha256sum"]
    else:
        return metadata["Sha256sum"]


def get_deltafile_schema_validator() -> jsonschema.Draft7Validator:
    """Creates a JSON schema validator to check whether the provided delta
    file is valid.

    Returns:
        jsonschema.Draft7Validator -- JSON Schema validator
    """
    schema_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "deltafile_01.json"
    )

    with open(schema_file) as f:
        schema_dict = json.load(f)

    jsonschema.Draft7Validator.check_schema(schema_dict)

    return jsonschema.Draft7Validator(schema_dict)


def get_project_files(project_id: str, path: str = "") -> list[S3Object]:
    """Returns a list of files and their versions.

    Args:
        project_id: the project id
        path: additional filter prefix

    Returns:
        the list of files

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    bucket = get_s3_bucket()
    root_prefix = f"projects/{project_id}/files/"
    prefix = f"projects/{project_id}/files/{path}"

    return list_files(bucket, prefix, root_prefix)


def get_project_package_files(project_id: str, package_id: str) -> list[S3Object]:
    """Returns a list of package files.

    Args:
        project_id: the project id

    Returns:
        the list of package files

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    bucket = get_s3_bucket()
    prefix = f"projects/{project_id}/packages/{package_id}/"

    return list_files(bucket, prefix, prefix)


def list_files(
    bucket: mypy_boto3_s3.service_resource.Bucket,
    prefix: str,
    strip_prefix: str = "",
) -> list[S3Object]:
    """List a bucket's objects under prefix.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    files = []
    for f in bucket.objects.filter(Prefix=prefix):
        if strip_prefix:
            start_idx = len(strip_prefix)
            name = f.key[start_idx:]
        else:
            name = f.key

        files.append(
            S3Object(
                name=name,
                key=f.key,
                last_modified=f.last_modified,
                size=f.size,
                etag=f.e_tag,
                md5sum=f.e_tag.replace('"', ""),
            )
        )

    files.sort(key=lambda f: f.name)

    return files


def get_file_storage_choices() -> list[tuple[str, str]]:
    """
    Returns configured storages keys.
    Can be used e.g. for ModelForm's field choices.
    """
    storages = list(settings.STORAGES.keys())[:-1]
    return [(storage, storage) for storage in storages]
