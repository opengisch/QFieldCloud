import logging

from django.test import TestCase, override_settings
from django.urls import reverse

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )

        self.client.force_login(self.superuser)

    def test_admin_environment_title_prefix(self):
        with self.subTest("Test production has no title prefix"):
            with override_settings(ENVIRONMENT="production"):
                resp = self.client.get(reverse("admin:index"))

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.context["environment_title_prefix"], "")

        with self.subTest("Test a non-production environment has a title prefix"):
            with override_settings(ENVIRONMENT="development"):
                resp = self.client.get(reverse("admin:index"))

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.context["environment_title_prefix"], "Development |")
            self.assertContains(resp, "<title>Development | ")
