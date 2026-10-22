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

    def _get_admin_index(self):
        resp = self.client.get(reverse("admin:index"))

        self.assertEqual(resp.status_code, 200)

        return resp

    def test_admin_shows_environment_banner(self):
        with self.subTest("Test production shows a red banner and no title prefix"):
            with override_settings(ENVIRONMENT="production"):
                resp = self._get_admin_index()

            self.assertEqual(resp.context["environment"], ["Production", "danger"])
            self.assertEqual(resp.context["environment_title_prefix"], "")

        with self.subTest("Test staging shows a blue banner and a title prefix"):
            with override_settings(ENVIRONMENT="staging"):
                resp = self._get_admin_index()

            self.assertEqual(resp.context["environment"], ["Staging", "info"])
            self.assertEqual(resp.context["environment_title_prefix"], "Staging |")

        with self.subTest(
            "Test development shows a blue banner and a title prefix in the page title"
        ):
            with override_settings(ENVIRONMENT="development"):
                resp = self._get_admin_index()

            self.assertEqual(resp.context["environment"], ["Development", "info"])
            self.assertContains(resp, "<title>Development | ")

        with self.subTest("Test test shows a blue banner and a title prefix"):
            with override_settings(ENVIRONMENT="test"):
                resp = self._get_admin_index()

            self.assertEqual(resp.context["environment"], ["Test", "info"])
            self.assertEqual(resp.context["environment_title_prefix"], "Test |")
