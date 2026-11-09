import json
import logging

from django.test import TestCase

from qfieldcloud.core.models import (
    Organization,
    Person,
    SealedSecretValue,
    Secret,
    WorkerPool,
)
from qfieldcloud.core.tests.test_sealed_box import TEST_PUBLIC_KEY, _open
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


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
        self.project1 = Project.objects.create(name="p1", owner=self.organization1)
        self.global_pool = WorkerPool.objects.create(
            name="global", public_key=TEST_PUBLIC_KEY
        )

    def _create_secret(self, **kwargs) -> Secret:
        return Secret.objects.create(
            name="SECRET1", type=Secret.Type.ENVVAR, value="grüezi", **kwargs
        )

    def _create_organization_pool(self, public_key=TEST_PUBLIC_KEY):
        return WorkerPool.objects.create(
            name="pool", organization=self.organization1, public_key=public_key
        )

    def test_payload_binds_value_to_secret_and_pool(self):
        secret = self._create_secret(project=self.project1)

        sealed_value = secret.sealed_values.get()

        self.assertEqual(sealed_value.pool, self.global_pool)
        self.assertEqual(sealed_value.key_id, self.global_pool.key_id)
        self.assertEqual(
            json.loads(_open(sealed_value.ciphertext)),
            {
                "secret_id": str(secret.pk),
                "pool_id": str(self.global_pool.pk),
                "name": "SECRET1",
                "type": "envvar",
                "value": "grüezi",
            },
        )

    def test_secret_is_sealed_for_the_organization_pool_only(self):
        pool = self._create_organization_pool()

        for kwargs in (
            {"project": self.project1},
            {"organization": self.organization1},
        ):
            with self.subTest(kwargs=kwargs):
                secret = self._create_secret(**kwargs)

                self.assertEqual(secret.sealed_values.get().pool, pool)

    def test_organization_secret_without_own_pool_is_sealed_for_global_pool(self):
        secret = self._create_secret(organization=self.organization1)

        self.assertEqual(secret.sealed_values.get().pool, self.global_pool)

    def test_pool_without_key_gets_no_sealed_value(self):
        self.global_pool.public_key = ""
        self.global_pool.save()

        secret = self._create_secret(project=self.project1)

        self.assertFalse(secret.sealed_values.exists())

    def test_organization_pool_without_key_never_falls_back_to_global(self):
        self._create_organization_pool(public_key="")

        secret = self._create_secret(project=self.project1)

        self.assertFalse(secret.sealed_values.exists())

    def test_saving_replaces_the_sealed_value(self):
        secret = self._create_secret(project=self.project1)
        old_ciphertext = secret.sealed_values.get().ciphertext

        secret.value = "new value"
        secret.save()

        sealed_value = SealedSecretValue.objects.get(secret=secret)
        self.assertNotEqual(sealed_value.ciphertext, old_ciphertext)
        self.assertEqual(
            json.loads(_open(sealed_value.ciphertext))["value"], "new value"
        )
