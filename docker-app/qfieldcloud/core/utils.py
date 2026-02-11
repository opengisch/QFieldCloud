import hashlib
import io
import json
import logging
import os
from typing import IO

import jsonschema
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

logger = logging.getLogger(__name__)


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
