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
            username="existing9928", password="abc123"
        )

    def test_generated_usernames(self):
        random.seed(42)
        expectations = [
            # Bases username on localpart of email plus random 4-digit suffix
            ("john@example.org", "john2824"),
            # Collisions with existing usernames are avoided
            ("existing@example.org", "existing99286"),
            # Letters are lowercased
            ("JOHN@example.org", "john1711"),
            # Non-ASCII characters are transliterated
            ("fööbär@example.org", "foobar8428"),
            # Special characters are stripped
            ("john.doe@example.org", "johndoe6168"),
            # Almomst all of them...
            ("john.+*?%$/doe@example.org", "johndoe7543"),
            # Except underscores and dashes, which are preserved
            ("john-peter_doe@example.org", "john-peter_doe2876"),
        ]

        adapter = AccountAdapter()
        user = Person.objects.create_user(username="temp", password="abc123")

        for email, expected in expectations:
            user.username = ""
            user.email = email
            adapter.populate_username(HttpRequest(), user)
            self.assertEqual(user.username, expected)
