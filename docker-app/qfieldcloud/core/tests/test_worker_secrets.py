import json
import logging

from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.core.models import Job, Organization, Person, Secret, WorkerPool
from qfieldcloud.core.tests.test_sealed_box import TEST_PUBLIC_KEY, _open
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.core.worker_pools import claim_job
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

OTHER_PUBLIC_KEY = "3p7bfXt9wbTTW2HC7OQ1Nz-DQ8hbeGdNrfx-FG-IK08="


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        set_subscription(self.user1)
        self.project1 = Project.objects.create(name="p1", owner=self.user1)
        self.pool = WorkerPool(name="global", public_key=TEST_PUBLIC_KEY)
        self.credential = self.pool.generate_credential()
        self.pool.save()
        self.job = Job.objects.create(
            project=self.project1,
            type=Job.Type.PACKAGE,
            created_by=self.user1,
            triggered_by=self.user1,
        )

    def _create_secret(self) -> Secret:
        return Secret.objects.create(
            name="SECRET1",
            type=Secret.Type.ENVVAR,
            value="value",
            project=self.project1,
        )

    def _fetch(self, credential=None):
        return self.client.post(
            f"/api/v1/worker/jobs/{self.job.pk}/secrets/",
            headers={"authorization": f"WorkerPool {credential or self.credential}"},
        )

    def test_fetch_requires_credential(self):
        response = self.client.post(f"/api/v1/worker/jobs/{self.job.pk}/secrets/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_fetch_returns_sealed_secrets_of_the_job(self):
        secret = self._create_secret()
        claim_job(self.pool)

        response = self._fetch()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sealed_secret = response.json()["secrets"][0]
        self.assertEqual(sealed_secret["secret_id"], secret.pk)
        self.assertEqual(
            json.loads(_open(sealed_secret["ciphertext"]))["value"], "value"
        )

    def test_fetch_without_secrets_is_empty(self):
        claim_job(self.pool)

        self.assertEqual(self._fetch().json(), {"secrets": []})

    def test_secrets_can_only_be_fetched_once(self):
        self._create_secret()
        claim_job(self.pool)
        self._fetch()

        self.assertEqual(self._fetch().status_code, status.HTTP_409_CONFLICT)

    def test_job_that_is_not_claimed_is_not_found(self):
        self.assertEqual(self._fetch().status_code, status.HTTP_404_NOT_FOUND)

    def test_job_of_another_pool_is_not_found(self):
        claim_job(self.pool)
        organization = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )
        other_pool = WorkerPool(name="own", organization=organization)
        other_credential = other_pool.generate_credential()
        other_pool.save()

        response = self._fetch(other_credential)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def _assert_job_failed_naming_secret(self, response):
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FAILED)
        self.assertIsNotNone(self.job.finished_at)
        self.assertIn("SECRET1", self.job.feedback["error"])
        self.assertIn("SECRET1", self.job.output)

    def test_secret_without_sealed_value_fails_the_job(self):
        secret = self._create_secret()
        secret.sealed_values.all().delete()
        claim_job(self.pool)

        self._assert_job_failed_naming_secret(self._fetch())

    def test_secret_sealed_with_an_old_key_fails_the_job(self):
        self._create_secret()
        self.pool.public_key = OTHER_PUBLIC_KEY
        self.pool.save()
        claim_job(self.pool)

        self._assert_job_failed_naming_secret(self._fetch())
