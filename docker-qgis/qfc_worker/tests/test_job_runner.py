import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from qfc_worker.job_runner import (
    REPORT_RETRY_INTERVAL_S,
    JobResult,
    get_feedback,
    report_result,
    run_job,
)

logging.disable(logging.CRITICAL)


def _response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code

    return response


class TestJobRunner(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.tempdir = Path(tempdir.name)
        self.output_path = self.tempdir.joinpath("output.txt")
        self.output_path.write_bytes(b"log")

    def _run_script(self, source: str, timeout_s: int = 30) -> JobResult:
        self.tempdir.joinpath("entrypoint.py").write_text(source)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tempdir)

        with mock.patch("qfc_worker.job_runner.XVFB_COMMAND", []):
            return run_job([], self.output_path, timeout_s)

    def test_output_and_exit_code_are_captured(self):
        result = self._run_script(
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
        )

        self.assertEqual(result, JobResult(exit_code=3, timed_out=False))
        self.assertIn(b"out", self.output_path.read_bytes())
        self.assertIn(b"err", self.output_path.read_bytes())

    def test_job_over_the_timeout_is_killed(self):
        result = self._run_script("import time; time.sleep(60)", timeout_s=1)

        self.assertTrue(result.timed_out)

    def test_exit_code_of_a_timeout_is_no_timeout(self):
        result = self._run_script("import sys; sys.exit(124)")

        self.assertEqual(result, JobResult(exit_code=124, timed_out=False))

    def test_missing_feedback_file_is_empty(self):
        self.assertEqual(get_feedback(Path("/nonexistent")), b"")

    def _report(self, result=JobResult(exit_code=0, timed_out=False), timeout_s=600):
        return report_result(
            "https://example.com/api/v1/",
            "job-token",
            "job-1",
            result,
            b"{}",
            self.output_path,
            timeout_s,
        )

    @mock.patch("qfc_worker.job_runner.requests.post")
    def test_report_sends_the_token_and_result(self, post):
        post.return_value = _response(204)

        self.assertTrue(self._report())
        self.assertEqual(
            post.call_args.args[0],
            "https://example.com/api/v1/worker/jobs/job-1/complete/",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"], {"Authorization": "Token job-token"}
        )
        self.assertEqual(
            post.call_args.kwargs["data"], {"exit_code": 0, "timed_out": False}
        )

    @mock.patch("qfc_worker.job_runner.requests.post")
    def test_report_tells_about_a_timeout(self, post):
        post.return_value = _response(204)

        self._report(JobResult(exit_code=-9, timed_out=True))

        self.assertEqual(
            post.call_args.kwargs["data"], {"exit_code": -9, "timed_out": True}
        )

    @mock.patch("qfc_worker.job_runner.time.sleep")
    @mock.patch("qfc_worker.job_runner.requests.post")
    def test_report_retries_when_unreachable(self, post, _sleep):
        post.side_effect = [requests.ConnectionError(), _response(204)]

        self.assertTrue(self._report())
        self.assertEqual(post.call_count, 2)

    @mock.patch("qfc_worker.job_runner.time.monotonic")
    @mock.patch("qfc_worker.job_runner.time.sleep")
    @mock.patch("qfc_worker.job_runner.requests.post")
    def test_report_gives_up_when_its_time_is_over(self, post, sleep, monotonic):
        clock = [0.0]
        monotonic.side_effect = lambda: clock[0]
        sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        post.return_value = _response(502)

        self.assertFalse(self._report(timeout_s=REPORT_RETRY_INTERVAL_S * 3))
        self.assertEqual(post.call_count, 3)
        self.assertLessEqual(
            post.call_args.kwargs["timeout"][1], REPORT_RETRY_INTERVAL_S
        )

    @mock.patch("qfc_worker.job_runner.requests.post")
    def test_refused_report_is_not_retried(self, post):
        post.return_value = _response(404)

        self.assertFalse(self._report())
        self.assertEqual(post.call_count, 1)
