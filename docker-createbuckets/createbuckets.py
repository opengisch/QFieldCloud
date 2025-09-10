#!/bin/env python3
import json
import os
import subprocess
from typing import TypedDict


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


STORAGES: dict[str, DjangoStorages] = json.loads(os.environ["STORAGES"])


for storage_name, storage_config in STORAGES.items():
    if storage_config["BACKEND"] != "qfieldcloud.filestorage.backend.QfcS3Boto3Storage":
        print(
            f'Skipping storage "{storage_name}" with backend `{storage_config["BACKEND"]}`, no need to create S3 bucket.'
        )
        continue

    print(f"Creating bucket for: {storage_name}", flush=True)

    endpoint_url = storage_config["OPTIONS"]["endpoint_url"]
    access_key = storage_config["OPTIONS"]["access_key"]
    secret_key = storage_config["OPTIONS"]["secret_key"]
    bucket_name = storage_config["OPTIONS"]["bucket_name"]

    subprocess.run(
        f"/usr/bin/mc alias set {storage_name} {endpoint_url} {access_key} {secret_key}",
        shell=True,
        check=True,
    )

    subprocess.run(
        f"/usr/bin/mc mb --ignore-existing {storage_name}/{bucket_name}",
        shell=True,
    )

    subprocess.run(
        f"/usr/bin/mc anonymous set download {storage_name}/{bucket_name}/users",
        shell=True,
        check=True,
    )

    # We should always enable versioning even for non-legacy storage, as we want to have soft delete on application level
    subprocess.run(
        f"/usr/bin/mc version enable {storage_name}/{bucket_name}",
        shell=True,
        check=True,
    )
