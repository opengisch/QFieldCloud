import json
import logging
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Job, Person, WorkerPool
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.core.worker_pools import claim_job
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        set_subscription(self.user1)
        self.project1 = Project.objects.create(name="p1", owner=self.user1)
        self.pool = WorkerPool.objects.create(name="global")
        self.job = Job.objects.create(
            project=self.project1, type=Job.Type.PACKAGE, created_by=self.user1
        )

    def _claim(self) -> str:
        return claim_job(self.pool).token

    def _complete(self, token, exit_code=0, feedback=b'{"outputs": {}}', output=b"log"):
        return self.client.post(
            f"/api/v1/worker/jobs/{self.job.pk}/complete/",
            {
                "exit_code": exit_code,
                "feedback": SimpleUploadedFile("feedback.json", feedback),
                "output": SimpleUploadedFile("output.txt", output),
            },
            format="multipart",
            headers={"authorization": f"Token {token}"},
        )

    def test_success_finishes_the_job(self):
        response = self._complete(self._claim())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FINISHED)
        self.assertIsNotNone(self.job.finished_at)
        self.assertEqual(self.job.output, "log")
        self.assertEqual(self.job.feedback["container_exit_code"], 0)

    def test_package_result_updates_the_project(self):
        self._complete(self._claim())

        self.job.refresh_from_db()
        self.project1.refresh_from_db()
        self.assertEqual(self.project1.data_last_packaged_at, self.job.started_at)

    def test_large_results_are_accepted(self):
        output = b"x" * (3 * 1000 * 1000)
        feedback = json.dumps({"outputs": {}, "padding": "x" * 3000000}).encode()

        response = self._complete(self._claim(), feedback=feedback, output=output)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FINISHED)
        self.assertEqual(len(self.job.output), len(output))

    def _assert_job_failed(self):
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FAILED)
        self.assertIsNotNone(self.job.finished_at)

    def test_non_zero_exit_code_fails_the_job(self):
        self._complete(self._claim(), exit_code=1)

        self._assert_job_failed()

    def test_error_in_feedback_fails_the_job(self):
        self._complete(self._claim(), feedback=b'{"error": "boom"}')

        self._assert_job_failed()
        self.assertEqual(self.job.feedback["error_origin"], "container")

    def test_invalid_feedback_fails_the_job(self):
        for feedback in (b"not json", b"[]"):
            with self.subTest(feedback=feedback):
                Job.objects.filter(pk=self.job.pk).update(
                    status=Job.Status.PENDING, worker_pool=None
                )

                self._complete(self._claim(), feedback=feedback)

                self._assert_job_failed()
                self.assertEqual(self.job.feedback["error_type"], "INVALID_RESULT")

    @mock.patch("qfieldcloud.core.worker_pools.MAX_JOB_RESULT_BYTES", 5)
    def test_too_large_feedback_fails_the_job(self):
        self._complete(self._claim(), feedback=b'{"outputs": {}}')

        self._assert_job_failed()
        self.assertEqual(self.job.feedback["error_type"], "RESULT_TOO_LARGE")

    def test_null_characters_in_output_are_removed(self):
        self._complete(self._claim(), output=b"a\x00b")

        self.job.refresh_from_db()
        self.assertEqual(self.job.output, "ab")

    def test_token_stops_working_after_completion(self):
        token = self._claim()
        self._complete(token)

        self.assertFalse(AuthToken.objects.get(key=token).is_active)

    def test_token_of_another_user_is_not_found(self):
        self._claim()
        other_user = Person.objects.create_user(username="other", password="abc123")
        token = AuthToken.objects.create(
            user=other_user, client_type=AuthToken.ClientType.WORKER
        )

        response = self._complete(token.key)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_token_of_another_job_of_the_same_user_is_not_found(self):
        other_job = Job.objects.create(
            project=Project.objects.create(name="p2", owner=self.user1),
            type=Job.Type.PACKAGE,
            created_by=self.user1,
        )
        self._claim()
        other_token = self._claim()

        self.assertEqual(AuthToken.objects.get(key=other_token).job_id, other_job.pk)
        self.assertEqual(
            self._complete(other_token).status_code, status.HTTP_404_NOT_FOUND
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.STARTED)

    def test_non_worker_token_is_rejected(self):
        self._claim()
        token = AuthToken.objects.create(
            user=self.user1, client_type=AuthToken.ClientType.CLI
        )

        response = self._complete(token.key)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_job_not_running_on_a_pool_is_not_found(self):
        token = AuthToken.objects.create(
            user=self.user1, client_type=AuthToken.ClientType.WORKER
        )
        Job.objects.filter(pk=self.job.pk).update(status=Job.Status.STARTED)

        response = self._complete(token.key)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
