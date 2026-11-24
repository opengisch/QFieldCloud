import logging
import time

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import (
    Person,
)
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
)
from qfieldcloud.project.models import (
    Project,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]
        self.project = Project.objects.create(
            name="The locked and unlocked project", owner=self.user1
        )

    def test_project_gets_locked(self):
        self.assertFalse(self.project.is_locked())

        self.project.lock(self.user1, is_explicit=False)
        self.project.refresh_from_db()

        self.assertEqual(self.project.lock_acquired_by, self.user1)
        self.assertIsNotNone(self.project.lock_expires_at)
        self.assertGreater(self.project.lock_expires_at, timezone.now())
        self.assertFalse(self.project.lock_is_explicit)
        self.assertTrue(self.project.is_locked())

    def test_project_gets_locked_then_unlocked(self):
        self.project.lock(self.user1, is_explicit=False)
        self.project.refresh_from_db()

        self.assertTrue(self.project.is_locked())

        self.project.unlock()
        self.project.refresh_from_db()

        self.assertIsNone(self.project.lock_acquired_by)
        self.assertIsNone(self.project.lock_expires_at)
        self.assertFalse(self.project.is_locked())

    @override_settings(QFIELDCLOUD_WORKER_TIMEOUT_S=3)
    def test_project_gets_unlocked_after_expiration(self):
        self.project.lock(self.user1, is_explicit=False)
        self.project.refresh_from_db()

        self.assertTrue(self.project.is_locked())

        time.sleep(settings.QFIELDCLOUD_WORKER_TIMEOUT_S + 1)
        self.project.refresh_from_db()

        self.assertFalse(self.project.is_locked())

    def test_can_not_lock_a_project_twice(self):
        self.project.lock(self.user1, is_explicit=False)
        self.project.refresh_from_db()

        self.assertTrue(self.project.is_locked())

        with self.assertRaises(exceptions.ProjectAlreadyLockedError):
            self.project.lock(self.user1, is_explicit=False)

    def test_project_gets_locked_then_unlocked_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(f"/api/v1/projects/{self.project.id}/lock/")
        response_json = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response_json["is_locked"])
        self.assertEqual(response_json["lock_acquired_by"], self.user1.username)
        self.assertIsNotNone(response_json["lock_expires_at"])
        self.assertTrue(response_json["lock_is_explicit"])

        lock_expires_at = parse_datetime(response_json["lock_expires_at"])

        self.assertIsNotNone(lock_expires_at)
        self.assertGreater(lock_expires_at, timezone.now())

        self.project.refresh_from_db()

        self.assertTrue(self.project.is_locked())
        self.assertTrue(self.project.lock_is_explicit)

        response = self.client.post(f"/api/v1/projects/{self.project.id}/unlock/")
        response_json = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response_json["is_locked"])
        self.assertIsNone(response_json.get("lock_acquired_by"))
        self.assertIsNone(response_json.get("lock_expires_at"))
        self.assertFalse(response_json.get("lock_is_explicit"))

        self.project.refresh_from_db()

        self.assertFalse(self.project.is_locked())
        self.assertFalse(self.project.lock_is_explicit)

    def test_can_not_unlock_a_project_that_is_not_locked_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(f"/api/v1/projects/{self.project.id}/unlock/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_not_lock_a_project_twice_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(f"/api/v1/projects/{self.project.id}/lock/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(f"/api/v1/projects/{self.project.id}/lock/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
