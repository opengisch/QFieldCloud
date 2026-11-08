import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from qfieldcloud.core.models import Organization, Person, WorkerPool
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)

PUBLIC_KEY = "6MzFDHAx0a-qfHUpgNla6WMlbJdZblPd4j4rxpbx5k8="


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

    def test_valid_public_key_is_accepted(self):
        pool = WorkerPool(
            name="pool", organization=self.organization1, public_key=PUBLIC_KEY
        )

        pool.full_clean()

    def test_pool_can_be_created_without_public_key(self):
        pool = WorkerPool(name="pool", organization=self.organization1)

        pool.full_clean()

    def test_invalid_public_key_is_rejected(self):
        pool = WorkerPool(
            name="pool", organization=self.organization1, public_key="invalid"
        )

        with self.assertRaises(ValidationError) as context:
            pool.full_clean()

        self.assertIn("public_key", context.exception.message_dict)

    def test_only_one_global_pool(self):
        WorkerPool.objects.create(name="global")

        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkerPool.objects.create(name="other")

    def test_only_one_pool_per_organization(self):
        WorkerPool.objects.create(name="pool", organization=self.organization1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkerPool.objects.create(name="other", organization=self.organization1)

    def test_effective_pool_without_any_pool_is_none(self):
        self.assertIsNone(WorkerPool.effective_for(self.organization1))

    def test_effective_pool_falls_back_to_global(self):
        global_pool = WorkerPool.objects.create(name="global")

        self.assertEqual(WorkerPool.effective_for(self.organization1), global_pool)
        self.assertEqual(WorkerPool.effective_for(self.user1), global_pool)

    def test_effective_pool_is_own_pool_even_without_key(self):
        WorkerPool.objects.create(name="global", public_key=PUBLIC_KEY)
        pool = WorkerPool.objects.create(name="pool", organization=self.organization1)

        self.assertEqual(WorkerPool.effective_for(self.organization1), pool)
