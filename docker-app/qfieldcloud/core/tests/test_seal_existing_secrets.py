import logging
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from qfieldcloud.core.models import (
    Organization,
    Person,
    SealedSecretValue,
    Secret,
    WorkerPool,
)
from qfieldcloud.core.tests.test_sealed_box import TEST_PUBLIC_KEY
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

        # created before any pool exists, like the secrets of an existing instance
        self.project_secret = Secret.objects.create(
            name="SECRET1",
            type=Secret.Type.ENVVAR,
            value="value",
            project=self.project1,
        )
        self.organization_secret = Secret.objects.create(
            name="SECRET2",
            type=Secret.Type.ENVVAR,
            value="value",
            organization=self.organization1,
        )

    def _run(self) -> str:
        output = StringIO()
        call_command("sealexistingsecrets", stdout=output)

        return output.getvalue().strip()

    def test_seals_existing_secrets_for_the_global_pool(self):
        pool = WorkerPool.objects.create(name="global", public_key=TEST_PUBLIC_KEY)

        self.assertEqual(self._run(), "Sealed 2, skipped 0 without a pool key.")

        self.assertEqual(self.project_secret.sealed_values.get().pool, pool)
        self.assertEqual(self.organization_secret.sealed_values.get().pool, pool)

    def test_running_again_keeps_the_sealed_values(self):
        WorkerPool.objects.create(name="global", public_key=TEST_PUBLIC_KEY)
        self._run()
        ciphertexts = set(
            SealedSecretValue.objects.values_list("ciphertext", flat=True)
        )

        self.assertEqual(self._run(), "Sealed 0, skipped 0 without a pool key.")

        self.assertEqual(
            set(SealedSecretValue.objects.values_list("ciphertext", flat=True)),
            ciphertexts,
        )

    def test_pool_without_key_is_skipped(self):
        WorkerPool.objects.create(name="global")

        self.assertEqual(self._run(), "Sealed 0, skipped 2 without a pool key.")

        self.assertFalse(SealedSecretValue.objects.exists())
