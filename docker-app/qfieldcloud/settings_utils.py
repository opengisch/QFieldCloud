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


class WebDavStorageOptions(TypedDict):
    webdav_url: str
    public_url: str
    basic_auth: str


class DjangoStorages(TypedDict):
    BACKEND: str
    OPTIONS: S3StorageOptions | WebDavStorageOptions
    QFC_IS_LEGACY: bool


class StoragesConfig(TypedDict):
    STORAGES: dict[str, DjangoStorages]


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
        raise ConfigValidationError("No STORAGES envvar configured!")

    if not isinstance(raw_storages, dict):
        raise ConfigValidationError(
            "Envvar STORAGES should be a JSON string that parses to dictionary!"
        )

    if "default" not in raw_storages:
        raise ConfigValidationError("Envvar STORAGES should contain a default storage!")

    for service_name, service_config in raw_storages.items():
        if not service_name:
            raise ConfigValidationError("Envvar `STORAGES` must have non-empty keys!")

        if (
            service_config["BACKEND"]
            != "qfieldcloud.filestorage.backend.QfcS3Boto3Storage"
            and service_config["BACKEND"]
            != "qfieldcloud.filestorage.backend.QfcWebDavStorage"
        ):
            raise ConfigValidationError(
                'Envvar `STORAGES[{}][BACKEND]` is expected to be "qfieldcloud.filestorage.backend.QfcS3Boto3Storage" or "qfieldcloud.filestorage.backend.QfcWebDavStorage", but "{}" given!'.format(
                    service_name, service_config["BACKEND"]
                )
            )

    return {
        "STORAGES": raw_storages,
    }


def get_socialaccount_providers_config() -> dict:
    providers_json: str = os.environ.get("SOCIALACCOUNT_PROVIDERS", "")

    if not providers_json:
        return {}

    try:
        providers = json.loads(providers_json)
    except Exception:
        raise ConfigValidationError(
            "Envvar SOCIALACCOUNT_PROVIDERS should be a parsable JSON string!"
        )

    if not isinstance(providers, dict):
        raise ConfigValidationError(
            "Envvar SOCIALACCOUNT_PROVIDERS should be a JSON string that parses to dictionary!"
        )

    return providers
