import logging
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.core.models import Person, WorkerPool
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)

PUBLIC_KEY = "6MzFDHAx0a-qfHUpgNla6WMlbJdZblPd4j4rxpbx5k8="
OTHER_PUBLIC_KEY = "3p7bfXt9wbTTW2HC7OQ1Nz-DQ8hbeGdNrfx-FG-IK08="


class QfcTestCase(APITestCase):
    def setUp(self):
        self.pool = WorkerPool(name="global")
        self.credential = self.pool.generate_credential()
        self.pool.save()

    def _register(self, credential=None, **data):
        return self.client.put(
            "/api/v1/worker/key/",
            data,
            format="json",
            headers={"authorization": f"WorkerPool {credential or self.credential}"},
        )

    def _login_superuser(self):
        setup_subscription_plans()
        superuser = Person.objects.create_superuser(username="super", password="abc123")
        self.client.force_login(superuser)

    def test_credential_is_not_stored(self):
        self.assertNotEqual(self.pool.credential_hash, self.credential)

    def test_register_sets_public_key(self):
        response = self._register(public_key=PUBLIC_KEY)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.public_key, PUBLIC_KEY)

    def test_register_refuses_pool_with_key_until_reset(self):
        self._register(public_key=PUBLIC_KEY)

        response = self._register(public_key=OTHER_PUBLIC_KEY)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.public_key, PUBLIC_KEY)

        self.pool.public_key = ""
        self.pool.save()

        response = self._register(public_key=OTHER_PUBLIC_KEY)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.public_key, OTHER_PUBLIC_KEY)

    def test_register_rejects_invalid_key(self):
        response = self._register(public_key="invalid")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.public_key, "")

    def test_register_requires_valid_credential(self):
        response = self._register(credential="wrong", public_key=PUBLIC_KEY)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.put(
            "/api/v1/worker/key/", {"public_key": PUBLIC_KEY}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_shows_credential_of_new_pool(self):
        WorkerPool.objects.all().delete()
        self._login_superuser()

        response = self.client.post(
            reverse("admin:core_workerpool_add"), {"name": "global"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        credential = response.context["pool_credentials"][0][1]
        self.assertContains(response, credential)
        self.assertEqual(
            WorkerPool.objects.get().credential_hash,
            WorkerPool.hash_credential(credential),
        )

    def test_admin_shows_error_for_invalid_public_key(self):
        self._login_superuser()

        response = self.client.post(
            reverse("admin:core_workerpool_change", args=[self.pool.pk]),
            {"name": "global", "public_key": "invalid"},
        )

        self.assertContains(response, "Invalid worker pool public key.")
        self.assertContains(response, 'name="public_key"')

    def test_global_pool_command(self):
        WorkerPool.objects.all().delete()
        output = StringIO()

        call_command("createglobalworkerpool", stdout=output)

        pool = WorkerPool.objects.get(organization__isnull=True)
        self.assertEqual(
            pool.credential_hash, WorkerPool.hash_credential(output.getvalue().strip())
        )

    def test_global_pool_command_keeps_credential_unless_asked(self):
        credential_hash = self.pool.credential_hash

        with self.assertRaises(CommandError):
            call_command("createglobalworkerpool", stdout=StringIO())

        self.pool.refresh_from_db()
        self.assertEqual(self.pool.credential_hash, credential_hash)

        call_command("createglobalworkerpool", "--new-credential", stdout=StringIO())

        self.pool.refresh_from_db()
        self.assertNotEqual(self.pool.credential_hash, credential_hash)
