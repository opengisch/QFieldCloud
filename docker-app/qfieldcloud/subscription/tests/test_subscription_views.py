import logging

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

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
