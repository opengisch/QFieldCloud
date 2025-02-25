import json
import os
from typing import TypedDict


class ConfigValidationError(Exception): ...


class S3StorageOptions(TypedDict):
    access_key: str
    secret_key: str
    bucket_name: str
    region_name: str
    endpoint_url: str


class DjangoStorages(TypedDict):
    BACKEND: str
    OPTIONS: S3StorageOptions
    QFC_IS_LEGACY: bool


class StoragesConfig(TypedDict):
    STORAGES: dict[str, DjangoStorages]
    LEGACY_STORAGE_NAME: str


def get_storages_config() -> StoragesConfig:
    raw_storages = {}
    storages_json: str = os.environ.get("STORAGES", "")

    if storages_json:
        try:
            raw_storages = json.loads(storages_json)
        except Exception:
            raise ConfigValidationError(
                "Envvar STORAGES should be a parsable JSON string!"
            )
    else:
        raw_storages["default"] = {
            "BACKEND": "qfieldcloud.filestorage.backend.QfcS3Boto3Storage",
            "OPTIONS": {
                "access_key": os.environ["STORAGE_ACCESS_KEY_ID"],
                "secret_key": os.environ["STORAGE_SECRET_ACCESS_KEY"],
                "bucket_name": os.environ["STORAGE_BUCKET_NAME"],
                "region_name": os.environ["STORAGE_REGION_NAME"],
                "endpoint_url": os.environ["STORAGE_ENDPOINT_URL"],
            },
            "QFC_IS_LEGACY": False,
        }

    if not isinstance(raw_storages, dict):
        raise ConfigValidationError(
            "Envvar STORAGES should be a JSON string that parses to dictionary!"
        )

    if "default" not in raw_storages:
        raise ConfigValidationError(
            "Envvar STORAGES_SERVICE_BY_DEFAULT should be non-empty string!"
        )

    legacy_storage_name = ""

    for service_name, service_config in raw_storages.items():
        if not service_name:
            raise ConfigValidationError("Envvar `STORAGES` must have non-empty keys!")

        if (
            service_config["BACKEND"]
            != "qfieldcloud.filestorage.backend.QfcS3Boto3Storage"
        ):
            raise ConfigValidationError(
                'Envvar `STORAGES[{}][BACKEND]` is expected to be "qfieldcloud.filestorage.backend.QfcS3Boto3Storage", but "{}" given!'.format(
                    service_name, service_config["BACKEND"]
                )
            )

        if service_config["QFC_IS_LEGACY"]:
            if legacy_storage_name:
                raise ConfigValidationError(
                    'There must be only one legacy storage, but both "{service_name}" and "{legacy_storage}" have `QFC_IS_LEGACY` set to `True`!'
                )

            legacy_storage_name = service_name

    return {
        "STORAGES": raw_storages,
        "LEGACY_STORAGE_NAME": legacy_storage_name,
    }
