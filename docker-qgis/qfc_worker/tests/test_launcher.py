import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from qfc_worker import launcher as launcher_module
from qfc_worker.launcher import (
    Launcher,
    LauncherError,
    clear_directory,
    get_runner_environment,
    report_failure,
    run,
)
from qfc_worker.sealed_box import generate_key_pair
from qfc_worker.tests.test_sealed_box import _seal

logging.disable(logging.CRITICAL)

URL = "https://example.com/api/v1/"
JOB = {
    "job_id": "job-1",
    "job_type": "package",
    "project_id": "project-1",
    "command": ["package", "project-1", "project.qgs", "qgiscore"],
    "token": "job-token",
    "timeout_s": 600,
    "report_timeout_s": 600,
}
SECRETS_MISSING = {"code": "job_secrets_missing", "message": "Missing"}


def _response(status_code: int, body: dict | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body or {}).encode()

    return response


class TestLauncher(unittest.TestCase):
    def setUp(self):
        self.key_pair = generate_key_pair()
        self.launcher = Launcher(URL, "credential", self.key_pair.private_key, 3)

    def _sealed(self, secret_id=1, name="SECRET1", type="envvar", value="value"):
        return {
            "secret_id": secret_id,
            "ciphertext": _seal(
                self.key_pair.public_key,
                json.dumps(
                    {"secret_id": "1", "name": name, "type": type, "value": value}
                ),
            ),
        }

    @mock.patch("qfc_worker.launcher.time.sleep")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_wait_for_job_retries_until_there_is_a_job(self, post, _sleep):
        post.side_effect = [_response(204), _response(200, JOB)]

        self.assertEqual(self.launcher.wait_for_job(), JOB)

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_run_does_not_claim_when_stopping(self, post, execve):
        self.launcher.is_stopping = True

        run(self.launcher)

        post.assert_not_called()
        execve.assert_not_called()

    @mock.patch("qfc_worker.launcher.time.sleep")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_stopping_ends_the_wait_between_claims(self, post, sleep):
        post.return_value = _response(204)

        def stop(_seconds):
            self.launcher.is_stopping = True

        sleep.side_effect = stop

        self.assertIsNone(self.launcher.wait_for_job())
        post.assert_called_once()
        sleep.assert_called_once()

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_claim_sends_the_qgis_version(self, post):
        post.return_value = _response(200, JOB)

        self.assertEqual(self.launcher.claim_job(), JOB)
        self.assertEqual(post.call_args.kwargs["json"], {"qgis_major_version": 3})

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_claim_without_job_or_connection_returns_none(self, post):
        post.return_value = _response(204)
        self.assertIsNone(self.launcher.claim_job())

        post.side_effect = requests.ConnectionError()
        self.assertIsNone(self.launcher.claim_job())

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_secrets_become_environment_variables(self, post):
        post.return_value = _response(200, {"secrets": [self._sealed()]})

        environment = self.launcher.fetch_environment_from_secrets("job-1")

        self.assertEqual(environment["SECRET1"], "value")
        self.assertEqual(environment["QFIELDCLOUD_EXTRA_ENVVARS"], '["SECRET1"]')

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_pgservice_secret_goes_to_the_service_file(self, post):
        post.return_value = _response(
            200, {"secrets": [self._sealed(type="pgservice", value="[a]\nhost=b")]}
        )

        environment = self.launcher.fetch_environment_from_secrets("job-1")

        self.assertEqual(environment["PGSERVICE_FILE_CONTENTS"], "\n[a]\nhost=b")
        self.assertNotIn("SECRET1", environment)

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_secret_sealed_for_another_identifier_is_rejected(self, post):
        post.return_value = _response(200, {"secrets": [self._sealed(secret_id=2)]})

        with self.assertRaises(LauncherError):
            self.launcher.fetch_environment_from_secrets("job-1")

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_secrets_the_app_refused_return_none(self, post):
        post.return_value = _response(409, SECRETS_MISSING)

        self.assertIsNone(self.launcher.fetch_environment_from_secrets("job-1"))

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_secrets_fetched_before_are_an_error(self, post):
        post.return_value = _response(409, {"code": "job_secrets_already_fetched"})

        with self.assertRaises(requests.HTTPError):
            self.launcher.fetch_environment_from_secrets("job-1")

    def test_runner_environment_has_no_pool_secrets(self):
        with mock.patch.dict(
            os.environ,
            {
                "QFIELDCLOUD_WORKER_POOL_CREDENTIAL": "credential",
                "QFIELDCLOUD_WORKER_PRIVATE_KEY": "private",
            },
        ):
            environment = get_runner_environment(JOB, {"SECRET1": "value"})

        self.assertNotIn("QFIELDCLOUD_WORKER_POOL_CREDENTIAL", environment)
        self.assertNotIn("QFIELDCLOUD_WORKER_PRIVATE_KEY", environment)
        self.assertEqual(environment["QFIELDCLOUD_TOKEN"], "job-token")
        self.assertEqual(environment["QFIELDCLOUD_REPORT_TIMEOUT_S"], "600")
        self.assertEqual(environment["SECRET1"], "value")

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_run_replaces_itself_with_the_job_runner(self, post, execve):
        post.side_effect = [_response(200, JOB), _response(200, {"secrets": []})]

        run(self.launcher)

        path, arguments, environment = execve.call_args.args
        self.assertEqual(path, sys.executable)
        self.assertEqual(
            arguments, [sys.executable, "-m", "qfc_worker.job_runner", *JOB["command"]]
        )
        self.assertEqual(environment["JOB_ID"], "job-1")

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_run_does_not_start_a_job_with_missing_secrets(self, post, execve):
        post.side_effect = [_response(200, JOB), _response(409, SECRETS_MISSING)]

        run(self.launcher)

        execve.assert_not_called()
        self.assertEqual(post.call_count, 2)

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_run_fails_the_job_when_secrets_were_fetched_before(self, post, execve):
        post.side_effect = [
            _response(200, JOB),
            _response(409, {"code": "job_secrets_already_fetched"}),
            _response(204),
        ]

        run(self.launcher)

        execve.assert_not_called()
        self.assertIn("/worker/jobs/job-1/complete/", post.call_args.args[0])

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_run_fails_the_job_when_secrets_cannot_be_opened(self, post, execve):
        broken = {"secret_id": 1, "ciphertext": "v1.broken"}
        post.side_effect = [
            _response(200, JOB),
            _response(200, {"secrets": [broken]}),
            _response(204),
        ]

        run(self.launcher)

        execve.assert_not_called()
        report = post.call_args
        self.assertIn("/worker/jobs/job-1/complete/", report.args[0])
        self.assertEqual(report.kwargs["headers"]["Authorization"], "Token job-token")
        self.assertEqual(report.kwargs["data"], {"exit_code": 1})

    @mock.patch("qfc_worker.launcher.requests.post")
    def test_failure_that_cannot_be_reported_is_logged(self, post):
        post.side_effect = requests.ConnectionError()
        # NOTE the module disables logging to keep the test output clean
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

        with self.assertLogs("LAUNCHER", logging.ERROR):
            report_failure(URL, JOB, "error")

    @mock.patch("qfc_worker.launcher.os.execve")
    @mock.patch("qfc_worker.launcher.requests.post")
    def test_delta_job_gets_its_deltafile(self, post, execve):
        delta_job = {**JOB, "job_type": "delta_apply"}
        post.side_effect = [
            _response(200, delta_job),
            _response(200, {"secrets": []}),
            _response(200, {"deltas": []}),
        ]

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(launcher_module, "IO_DIR", Path(tempdir)):
                run(self.launcher)

            self.assertEqual(
                json.loads(Path(tempdir, "deltafile.json").read_text()),
                {"deltas": []},
            )

        execve.assert_called_once()


class TestClearDirectory(unittest.TestCase):
    def test_removes_files_and_directories(self):
        with tempfile.TemporaryDirectory() as tempdir:
            directory = Path(tempdir)
            directory.joinpath("project/files").mkdir(parents=True)
            directory.joinpath("project/files/data.gpkg").write_text("data")
            directory.joinpath("file.txt").write_text("data")
            directory.joinpath("link").symlink_to("file.txt")

            clear_directory(directory)

            self.assertEqual(list(directory.iterdir()), [])

    def test_removes_directories_without_permissions(self):
        with tempfile.TemporaryDirectory() as tempdir:
            directory = Path(tempdir)
            nested = directory.joinpath("project/hidden")
            nested.mkdir(parents=True)
            nested.joinpath("data.gpkg").write_text("data")
            nested.chmod(0)
            nested.parent.chmod(0)

            clear_directory(directory)

            self.assertEqual(list(directory.iterdir()), [])

    def test_keeps_files_of_other_users(self):
        with tempfile.TemporaryDirectory() as tempdir:
            directory = Path(tempdir)
            file = directory.joinpath("requirements.txt")
            file.write_text("data")

            with mock.patch(
                "qfc_worker.launcher.os.getuid", return_value=os.getuid() + 1
            ):
                clear_directory(directory)

            self.assertTrue(file.exists())
