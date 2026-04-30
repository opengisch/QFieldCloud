import io
import json
import logging
import os
from datetime import datetime
from pathlib import PurePath
from typing import IO, NamedTuple

import jsonschema
import mypy_boto3_s3
from django.conf import settings

logger = logging.getLogger(__name__)


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


def get_file_storage_choices() -> list[tuple[str, str]]:
    """
    Returns configured storages keys.
    Can be used e.g. for ModelForm's field choices.
    """
    storages = list(settings.STORAGES.keys())[:-1]
    return [(storage, storage) for storage in storages]
