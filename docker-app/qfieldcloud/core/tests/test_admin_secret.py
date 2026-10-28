import logging

from django.test import TestCase
from django.urls import reverse

from qfieldcloud.core.models import Organization, Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.organization = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )

    def test_add_secret_action_requires_add_secret_permission(self):
        staff_user = Person.objects.create_user(
            username="staff", password="secret", is_staff=True
        )
        self.client.force_login(staff_user)

        resp = self.client.get(
            reverse("admin:core_organization_add_secret", args=[self.organization.pk])
        )

        self.assertEqual(resp.status_code, 403)
