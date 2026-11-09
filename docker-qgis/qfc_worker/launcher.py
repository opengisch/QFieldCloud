#!/usr/bin/env python3
"""Claims one job from QFieldCloud, prepares it and replaces itself with the job runner.

The pool credential and the private key only exist in this process. They are removed
from the environment of the job runner, so project code can never read them.

Usage: python3 -m qfc_worker.launcher
"""

import json
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

import requests

from qfc_worker.sealed_box import SealedBoxError, unseal

logger = logging.getLogger("LAUNCHER")

REQUEST_TIMEOUT_S = 60
CLAIM_INTERVAL_S = 5
IO_DIR = Path("/io")
TEMPORARY_DIRECTORIES = (Path("/tmp"), Path("/var/tmp"))
PRIVATE_ENVIRONMENT_VARIABLES = (
    "QFIELDCLOUD_WORKER_POOL_CREDENTIAL",
    "QFIELDCLOUD_WORKER_PRIVATE_KEY",
)
# The error code of the app when it failed the job itself, as the job needs secrets the pool cannot read.
SECRETS_MISSING_ERROR_CODE = "job_secrets_missing"
ENVVAR_SECRET_TYPE = "envvar"
PGSERVICE_SECRET_TYPE = "pgservice"


class LauncherError(Exception):
    pass


class Launcher:
    """Talks to QFieldCloud with the pool credential, and is the only holder of it and of the private key."""

    def __init__(
        self, url: str, credential: str, private_key: str, qgis_major_version: int
    ) -> None:
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"WorkerPool {credential}"}
        self.private_key = private_key
        self.qgis_major_version = qgis_major_version
        self.is_stopping = False

    def wait_for_job(self) -> dict[str, Any] | None:
        """Returns the next job, or `None` if the launcher was told to stop."""
        while not self.is_stopping:
            job = self.claim_job()

            if job:
                return job

            for _ in range(CLAIM_INTERVAL_S):
                if self.is_stopping:
                    break

                time.sleep(1)

        return None

    def claim_job(self) -> dict[str, Any] | None:
        """Returns the next job, or `None` if there is no job or QFieldCloud cannot be reached."""
        try:
            response = requests.post(
                f"{self.url}/worker/jobs/claim/",
                json={"qgis_major_version": self.qgis_major_version},
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as err:
            logger.warning("Cannot reach QFieldCloud: %s", err)
            return None

        if response.status_code == requests.codes.no_content:
            return None

        if not response.ok:
            logger.warning("Claiming a job got status %s", response.status_code)
            return None

        return response.json()

    def fetch_environment_from_secrets(self, job_id: str) -> dict[str, str] | None:
        """Returns the environment variables with the secrets of a job, `None` if the app failed the job for missing secrets."""
        response = requests.post(
            f"{self.url}/worker/jobs/{job_id}/secrets/",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_S,
        )

        # NOTE any other refusal, such as secrets that were already fetched, leaves the job to the worker to fail
        if (
            response.status_code == requests.codes.conflict
            and response.json().get("code") == SECRETS_MISSING_ERROR_CODE
        ):
            return None

        response.raise_for_status()

        return self._get_environment(response.json()["secrets"])

    def _get_environment(self, sealed_secrets: list[dict[str, Any]]) -> dict[str, str]:
        """Opens the secrets and returns them as environment variables for the job.

        Raises:
            SealedBoxError: if a secret cannot be opened with the private key.
            LauncherError: if a secret does not match its identifier or has an unknown type.
        """
        extra_envvars = {}
        pgservice_file_contents = ""

        for sealed_secret in sealed_secrets:
            secret = json.loads(
                unseal(private_key=self.private_key, sealed=sealed_secret["ciphertext"])
            )

            # a value sealed for one secret must not be accepted as another one
            if secret["secret_id"] != str(sealed_secret["secret_id"]):
                raise LauncherError("A sealed secret does not match its identifier.")

            if secret["type"] == ENVVAR_SECRET_TYPE:
                extra_envvars[secret["name"]] = secret["value"]
            elif secret["type"] == PGSERVICE_SECRET_TYPE:
                pgservice_file_contents += f"\n{secret['value']}"
            else:
                raise LauncherError(f"Unknown secret type: {secret['type']}")

        return {
            **extra_envvars,
            "PGSERVICE_FILE_CONTENTS": pgservice_file_contents,
            "QFIELDCLOUD_EXTRA_ENVVARS": json.dumps(sorted(extra_envvars.keys())),
        }

    def write_deltafile(self, job_id: str) -> None:
        """Downloads the deltafile of a delta job to `IO_DIR`, which works only once per job."""
        response = requests.post(
            f"{self.url}/worker/jobs/{job_id}/deltafile/",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()

        IO_DIR.joinpath("deltafile.json").write_bytes(response.content)


def clear_directory(directory: Path) -> None:
    """Removes what this user left in `directory`, files of the image stay."""
    for child in directory.iterdir():
        if child.lstat().st_uid != os.getuid():
            continue

        if child.is_symlink() or not child.is_dir():
            child.unlink()
            continue

        # a job could have taken away its own permissions to keep files for the next job
        child.chmod(0o700)
        for root, dirnames, _filenames in os.walk(child):
            for dirname in dirnames:
                path = Path(root, dirname)

                if not path.is_symlink():
                    path.chmod(0o700)

        shutil.rmtree(child)


def get_runner_environment(
    job: dict[str, Any], secrets_environment: dict[str, str]
) -> dict[str, str]:
    """Returns the environment of the job runner, which never contains the pool credential or the private key."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in PRIVATE_ENVIRONMENT_VARIABLES
    }

    return {
        **environment,
        **secrets_environment,
        "QFIELDCLOUD_TOKEN": job["token"],
        "JOB_ID": str(job["job_id"]),
        "QFIELDCLOUD_WORKER_TIMEOUT_S": str(job["timeout_s"]),
        "QFIELDCLOUD_REPORT_TIMEOUT_S": str(job["report_timeout_s"]),
        "QT_QPA_PLATFORM": "offscreen",
    }


def report_failure(url: str, job: dict[str, Any], error: str) -> None:
    """Fails a job that cannot start, with the token of the job.

    If the app cannot be told, the job is failed once its time limit is over.
    """
    try:
        response = requests.post(
            f"{url.rstrip('/')}/worker/jobs/{job['job_id']}/complete/",
            data={"exit_code": 1},
            files={
                "feedback": json.dumps({"error": error, "error_type": "WORKER_SETUP"}),
                "output": error,
            },
            headers={"Authorization": f"Token {job['token']}"},
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as err:
        logger.error("Cannot report the failure of job %s: %s", job["job_id"], err)
        return

    if not response.ok:
        logger.error(
            "Reporting the failure of job %s got status %s",
            job["job_id"],
            response.status_code,
        )


def run(launcher: Launcher) -> None:
    """Waits for a job and starts it. Only returns if told to stop or the job could not be started."""
    job = launcher.wait_for_job()

    if not job:
        return

    job_id = str(job["job_id"])

    try:
        secrets_environment = launcher.fetch_environment_from_secrets(job_id)

        # the app already failed the job and told the user which secrets are missing
        if secrets_environment is None:
            return

        if job["job_type"] == "delta_apply":
            launcher.write_deltafile(job_id)
    except (LauncherError, SealedBoxError, requests.RequestException, KeyError) as err:
        logger.error("Failed to start job %s: %s", job_id, type(err).__name__)
        report_failure(
            launcher.url,
            job,
            "The worker could not read the secrets or data of this job.",
        )
        return

    os.execve(
        sys.executable,
        [sys.executable, "-m", "qfc_worker.job_runner", *job["command"]],
        get_runner_environment(job, secrets_environment),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    try:
        launcher = Launcher(
            os.environ["QFIELDCLOUD_URL"],
            os.environ["QFIELDCLOUD_WORKER_POOL_CREDENTIAL"],
            os.environ["QFIELDCLOUD_WORKER_PRIVATE_KEY"],
            int(os.environ.get("QFIELDCLOUD_WORKER_QGIS_MAJOR_VERSION", "3")),
        )
    except KeyError as err:
        sys.exit(f"Missing environment variable {err}.")

    # NOTE the first process of a container ignores SIGTERM without a handler. The handler only ends the wait for a job, a claimed job still runs, and the job runner keeps ignoring SIGTERM until the job is done.
    def stop(_signum: int, _frame: Any) -> None:
        launcher.is_stopping = True

    signal.signal(signal.SIGTERM, stop)

    # NOTE a restarted container keeps its disk, the files of a job must not reach the next one
    try:
        for directory in TEMPORARY_DIRECTORIES:
            clear_directory(directory)
    except OSError as err:
        sys.exit(f"Cannot clear the files of the previous job: {err}")

    run(launcher)


if __name__ == "__main__":
    main()
