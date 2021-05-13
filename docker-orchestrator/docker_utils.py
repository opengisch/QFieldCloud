import os
from typing import Dict

import docker

QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)

assert QGIS_CONTAINER_NAME
assert QFIELDCLOUD_HOST


def run_docker(command: str, volumes: Dict[str, str] = {}):
    client = docker.from_env()
    container = client.containers.create(
        QGIS_CONTAINER_NAME,
        environment={
            "STORAGE_ACCESS_KEY_ID": os.environ.get("STORAGE_ACCESS_KEY_ID"),
            "STORAGE_SECRET_ACCESS_KEY": os.environ.get("STORAGE_SECRET_ACCESS_KEY"),
            "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
            "STORAGE_REGION_NAME": os.environ.get("STORAGE_REGION_NAME"),
            "STORAGE_ENDPOINT_URL": os.environ.get("STORAGE_ENDPOINT_URL"),
        },
        auto_remove=True,
        volumes=volumes,
        network_mode=("host" if QFIELDCLOUD_HOST == "localhost" else "bridge"),
    )

    container.start()
    container.attach(logs=True)

    exit_code, output = container.exec_run(command)

    container.kill()

    return exit_code, output
