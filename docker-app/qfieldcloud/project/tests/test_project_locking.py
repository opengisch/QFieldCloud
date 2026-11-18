import logging
import time

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

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
        self.project = Project(name="The locked and unlocked project", owner=self.user1)

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
