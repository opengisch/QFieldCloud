#!/usr/bin/env python3
"""Runs one job started by the launcher and reports its result to QFieldCloud.

It only knows the token of the job, the launcher removed the pool credential and the private key.

Usage: python3 -m qfc_worker.job_runner COMMAND [ARGUMENT ...]
"""

import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, NamedTuple

import requests

logger = logging.getLogger("JOBRUNNR")

# NOTE only around the job and not as the entrypoint of the worker container, because a parent process would keep the pool credential and the private key in its environment
XVFB_COMMAND = ["/usr/bin/xvfb-run", "-a"]
FEEDBACK_FILE = Path("/io/feedback.json")
REPORT_CONNECT_TIMEOUT_S = 30
REPORT_READ_TIMEOUT_S = 300
REPORT_RETRY_INTERVAL_S = 10


class JobResult(NamedTuple):
    """How a job ended."""

    exit_code: int
    timed_out: bool


def run_job(command: list[str], output_path: Path, timeout_s: int) -> JobResult:
    """Runs the job and returns how it ended, its output goes to `output_path`."""
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            [*XVFB_COMMAND, sys.executable, "entrypoint.py", *command],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        try:
            return JobResult(process.wait(timeout=timeout_s), timed_out=False)
        except subprocess.TimeoutExpired:
            # the whole process group, as QGIS might have started its own processes
            os.killpg(process.pid, signal.SIGKILL)

            return JobResult(process.wait(), timed_out=True)


def get_feedback(feedback_file: Path) -> bytes:
    """Returns the feedback the job wrote, empty if it wrote none."""
    try:
        return feedback_file.read_bytes()
    except OSError:
        return b""


def report_result(
    url: str,
    token: str,
    job_id: str,
    result: JobResult,
    feedback: bytes,
    output_path: Path,
    report_timeout_s: int,
) -> bool:
    """Sends the result to QFieldCloud, retrying within `report_timeout_s` when it cannot be reached. Returns whether it was accepted.

    NOTE the app keeps the token of the job valid for `report_timeout_s` after the job timeout, and fails the job afterwards.
    """
    deadline = time.monotonic() + report_timeout_s

    while True:
        remaining_s = deadline - time.monotonic()

        try:
            with output_path.open("rb") as output:
                files: dict[str, IO[bytes] | bytes] = {
                    "feedback": feedback,
                    "output": output,
                }
                response = requests.post(
                    f"{url.rstrip('/')}/worker/jobs/{job_id}/complete/",
                    data={
                        "exit_code": result.exit_code,
                        "timed_out": result.timed_out,
                    },
                    files=files,
                    headers={"Authorization": f"Token {token}"},
                    timeout=(
                        REPORT_CONNECT_TIMEOUT_S,
                        max(1, min(REPORT_READ_TIMEOUT_S, remaining_s)),
                    ),
                )

            if response.ok:
                return True

            logger.error("Reporting the result got status %s", response.status_code)

            # the answer will not change for a request the app refused
            if response.status_code < requests.codes.server_error:
                return False
        except requests.RequestException as err:
            logger.warning("Cannot reach QFieldCloud: %s", type(err).__name__)

        if deadline - time.monotonic() <= REPORT_RETRY_INTERVAL_S:
            return False

        time.sleep(REPORT_RETRY_INTERVAL_S)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    with tempfile.TemporaryDirectory() as tempdir:
        output_path = Path(tempdir).joinpath("output.txt")

        result = run_job(
            sys.argv[1:],
            output_path,
            int(os.environ["QFIELDCLOUD_WORKER_TIMEOUT_S"]),
        )

        is_reported = report_result(
            os.environ["QFIELDCLOUD_URL"],
            os.environ["QFIELDCLOUD_TOKEN"],
            os.environ["JOB_ID"],
            result,
            get_feedback(FEEDBACK_FILE),
            output_path,
            int(os.environ["QFIELDCLOUD_REPORT_TIMEOUT_S"]),
        )

    if not is_reported:
        sys.exit("Could not report the result of the job.")


if __name__ == "__main__":
    main()
