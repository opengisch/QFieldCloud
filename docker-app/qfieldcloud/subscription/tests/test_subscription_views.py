import logging

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, OrganizationMember, Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )

    def test_get_account_subscription(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/api/v1/subscriptions/{self.user1.username}/current/",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["uuid"], str(self.user1.useraccount.current_subscription.uuid)
        )
        self.assertEqual(
            response.data["plan_display_name"],
            self.user1.useraccount.current_subscription.plan.display_name,
        )

    def test_get_organization_subscription(self):
        # check if owner can access the subscription
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/api/v1/subscriptions/{self.organization1.username}/current/",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["uuid"],
            str(self.organization1.useraccount.current_subscription.uuid),
        )
        self.assertEqual(
            response.data["plan_display_name"],
            self.organization1.useraccount.current_subscription.plan.display_name,
        )

        # check if member can access the subscription
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        response = self.client.get(
            f"/api/v1/subscriptions/{self.organization1.username}/current/",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["uuid"],
            str(self.organization1.useraccount.current_subscription.uuid),
        )
        self.assertEqual(
            response.data["plan_display_name"],
            self.organization1.useraccount.current_subscription.plan.display_name,
        )

        # check if other user cannot access the subscription
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)
        response = self.client.get(
            f"/api/v1/subscriptions/{self.organization1.username}/current/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
