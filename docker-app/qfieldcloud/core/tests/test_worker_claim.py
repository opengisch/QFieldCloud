import logging
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Job, Organization, Person, WorkerPool
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )
        set_subscription(self.user1)
        set_subscription(self.organization1)
        self.person_project = Project.objects.create(name="p1", owner=self.user1)
        self.organization_project = Project.objects.create(
            name="p2", owner=self.organization1
        )
        self.global_pool, self.global_credential = self._create_pool("global")

    def _create_pool(self, name, organization=None):
        pool = WorkerPool(name=name, organization=organization)
        credential = pool.generate_credential()
        pool.save()

        return pool, credential

    def _create_job(self, project):
        return Job.objects.create(
            project=project, type=Job.Type.PACKAGE, created_by=self.user1
        )

    def _claim(self, credential=None):
        return self.client.post(
            "/api/v1/worker/jobs/claim/",
            headers={
                "authorization": f"WorkerPool {credential or self.global_credential}"
            },
        )

    def test_claim_requires_credential(self):
        response = self.client.post("/api/v1/worker/jobs/claim/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_call_updates_last_seen(self):
        self.assertIsNone(self.global_pool.last_seen_at)

        self._claim()

        self.global_pool.refresh_from_db()
        self.assertIsNotNone(self.global_pool.last_seen_at)

    def test_last_seen_is_written_once_per_interval(self):
        recently = timezone.now() - timedelta(seconds=10)
        WorkerPool.objects.update(last_seen_at=recently)

        self._claim()

        self.global_pool.refresh_from_db()
        self.assertEqual(self.global_pool.last_seen_at, recently)

        WorkerPool.objects.update(last_seen_at=recently - timedelta(minutes=1))

        self._claim()

        self.global_pool.refresh_from_db()
        self.assertGreater(self.global_pool.last_seen_at, recently)

    def test_claim_without_jobs(self):
        self.assertEqual(self._claim().status_code, status.HTTP_204_NO_CONTENT)

    def test_claim_starts_the_oldest_job(self):
        job = self._create_job(self.person_project)
        self._create_job(self.organization_project)

        response = self._claim()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["job_id"], str(job.pk))
        self.assertEqual(response.json()["project_id"], str(self.person_project.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.STARTED)
        self.assertIsNotNone(job.started_at)
        self.assertEqual(job.worker_pool, self.global_pool)

    def test_claim_returns_a_worker_token_of_the_job_creator(self):
        self._create_job(self.person_project)

        token = AuthToken.objects.get(key=self._claim().json()["token"])

        self.assertEqual(token.user, self.user1)
        self.assertEqual(token.client_type, AuthToken.ClientType.WORKER)
        self.assertGreater(token.expires_at, timezone.now())

    def test_project_runs_one_job_at_a_time(self):
        self._create_job(self.person_project)
        self._create_job(self.person_project)

        self.assertEqual(self._claim().status_code, status.HTTP_200_OK)
        self.assertEqual(self._claim().status_code, status.HTTP_204_NO_CONTENT)

    def test_locked_project_is_skipped(self):
        self._create_job(self.person_project)
        Project.objects.update(locked_at=timezone.now())

        self.assertEqual(self._claim().status_code, status.HTTP_204_NO_CONTENT)

    def test_job_without_creator_is_skipped(self):
        job = self._create_job(self.person_project)
        Job.objects.filter(pk=job.pk).update(created_by=None)

        self.assertEqual(self._claim().status_code, status.HTTP_204_NO_CONTENT)

    def test_organization_pool_only_claims_its_own_jobs(self):
        _pool, credential = self._create_pool("own", self.organization1)
        self._create_job(self.person_project)
        job = self._create_job(self.organization_project)

        self.assertEqual(self._claim(credential).json()["job_id"], str(job.pk))
        self.assertEqual(
            self._claim(credential).status_code, status.HTTP_204_NO_CONTENT
        )

    def test_global_pool_skips_organizations_with_own_pool(self):
        self._create_pool("own", self.organization1)
        job = self._create_job(self.organization_project)

        self.assertEqual(self._claim().status_code, status.HTTP_204_NO_CONTENT)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.PENDING)

    def test_admin_shows_last_job_of_pool(self):
        job = self._create_job(self.person_project)
        self._claim()
        self.client.force_login(
            Person.objects.create_superuser(username="super", password="abc123")
        )

        response = self.client.get(
            reverse("admin:core_workerpool_change", args=[self.global_pool.pk])
        )

        self.assertContains(response, reverse("admin:core_job_change", args=[job.pk]))
