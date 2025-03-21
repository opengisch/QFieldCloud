import logging
import random

from django.http import HttpRequest
from django.test.testcases import TransactionTestCase

from qfieldcloud.core.adapters import AccountAdapter
from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(TransactionTestCase):
    def setUp(self):
        setup_subscription_plans()
        self.existing_user = Person.objects.create_user(
            username="existing2824", password="abc123"
        )

    def test_generated_usernames_avoid_collisions(self):
        random.seed(42)
        expectations = [
            # Collisions with existing usernames are avoided
            ("existing@example.org", "existing28240"),
        ]

        adapter = AccountAdapter()
        user = Person.objects.create_user(username="temp", password="abc123")

        for email, expected in expectations:
            user.username = ""
            user.email = email
            adapter.populate_username(HttpRequest(), user)
            self.assertEqual(user.username, expected)
