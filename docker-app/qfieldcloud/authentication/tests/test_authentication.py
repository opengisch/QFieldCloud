import logging

from django.utils.timezone import datetime, now
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, Person, Team
from qfieldcloud.core.tests.utils import setup_subscription_plans
from rest_framework.test import APITransactionTestCase

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")

    def assertTokenMatch(self, token, payload):
        expires_at = payload.pop("expires_at")
        avatar_url = payload.pop("avatar_url")
        self.assertDictEqual(
            payload,
            {
                "token": token.key,
                # "expires_at": tokens[0].expires_at.isoformat(),
                "username": token.user.username,
                "email": "",
                "first_name": "",
                "full_name": "",
                "last_name": "",
                "type": "1",
            },
        )
        self.assertTrue(datetime.fromisoformat(expires_at) == token.expires_at)
        self.assertTrue(datetime.fromisoformat(expires_at) > now())
        self.assertTrue(avatar_url is None or avatar_url.startswith("http"))
        self.assertTrue(
            avatar_url is None
            or avatar_url.endswith(
                f"/api/v1/files/public/users/{token.user.username}/avatar.svg"
            )
        )

    def login(self, username, password, user_agent="", success=True):
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": username,
                "password": password,
            },
            HTTP_USER_AGENT=user_agent,
        )

        if success:
            self.assertEqual(response.status_code, 200)

        return response

    def test_login_logout(self):
        response = self.login("user1", "abc123")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 1)
        self.assertTokenMatch(tokens[0], response.json())
        self.assertGreater(tokens[0].expires_at, now())

        # set auth token
        self.client.credentials(HTTP_AUTHORIZATION="Token " + tokens[0].key)

        # logout
        response = self.client.post("/api/v1/auth/logout/")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(tokens), 1)
        self.assertLess(tokens[0].expires_at, now())

    def test_multiple_logins(self):
        # first single active token login
        response = self.login("user1", "abc123", "Mozilla/5.0 QGIS/32203")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 1)
        self.assertTokenMatch(tokens[0], response.json())

        # second single active token login
        response = self.login("user1", "abc123", "Mozilla/5.0 QGIS/32203")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 2)
        self.assertTokenMatch(tokens[0], response.json())
        self.assertNotEqual(tokens[0], tokens[1])
        self.assertGreater(tokens[0].expires_at, now())
        self.assertLess(tokens[1].expires_at, now())

        # first single active token login
        response = self.login("user1", "abc123", "sdk|py|dev python-requests|2.26.0")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 3)
        self.assertTokenMatch(tokens[0], response.json())

        # second single active token login
        response = self.login("user1", "abc123", "sdk|py|dev python-requests|2.26.0")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 4)
        self.assertTokenMatch(tokens[0], response.json())
        self.assertNotEqual(tokens[0], tokens[1])
        self.assertGreater(tokens[0].expires_at, now())
        self.assertGreater(tokens[1].expires_at, now())

    def test_client_type(self):
        # QFIELDSYNC login
        response = self.login("user1", "abc123", "Mozilla/5.0 QGIS/32203")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.QFIELDSYNC)

        response = self.login(
            "user1", "abc123", "Mozilla/5.0 QGIS/32400/Ubuntu 20.04.4 LTS"
        )
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.QFIELDSYNC)

        # SDK login
        response = self.login("user1", "abc123", "sdk|py|dev python-requests|2.26.0")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.SDK)

        # BROWSER login
        response = self.login(
            "user1",
            "abc123",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:97.0) Gecko/20100101 Firefox/97.0",
        )
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.BROWSER)

        response = self.login(
            "user1",
            "abc123",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.105 Safari/537.36",
        )
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.BROWSER)

        # QFIELD login
        response = self.login(
            "user1",
            "abc123",
            "qfield|1.0.0|local - dev|3515ce8cba0f0e0abb92e06bf30a00531810656f| QGIS/31900",
        )
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.QFIELD)

        # UNKNOWN login
        response = self.login("user1", "abc123", "Слава Україні!")
        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertTokenMatch(tokens[0], response.json())
        self.assertEqual(tokens[0].client_type, AuthToken.ClientType.UNKNOWN)

    def test_last_used_at(self):
        response = self.login("user1", "abc123")

        tokens = self.user1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 1)
        self.assertTokenMatch(tokens[0], response.json())
        self.assertIsNone(tokens[0].last_used_at)

        # set auth token
        self.client.credentials(HTTP_AUTHORIZATION="Token " + tokens[0].key)

        # first token usage
        response = self.client.get(f"/api/v1/users/{self.user1.username}/")

        self.assertEqual(response.status_code, 200)

        tokens = self.user1.auth_tokens.order_by("-created_at").all()
        first_used_at = tokens[0].last_used_at

        self.assertEqual(len(tokens), 1)

        # second token usage
        response = self.client.get(f"/api/v1/users/{self.user1.username}/")

        self.assertEqual(response.status_code, 200)

        tokens = self.user1.auth_tokens.order_by("-created_at").all()
        second_used_at = tokens[0].last_used_at

        self.assertEqual(len(tokens), 1)
        self.assertLess(first_used_at, second_used_at)

    def test_login_users_only(self):
        u1 = Person.objects.create_user(username="u1", password="abc123")
        o1 = Organization.objects.create_user(
            username="o1", password="abc123", organization_owner=u1
        )
        t1 = Team.objects.create_user(
            username="@o1/t1", password="abc123", team_organization=o1
        )

        # regular users can login
        response = self.login("u1", "abc123", success=True)

        tokens = u1.auth_tokens.order_by("-created_at").all()

        self.assertEqual(len(tokens), 1)
        self.assertEqual(o1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertEqual(t1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertTokenMatch(tokens[0], response.json())
        self.assertIsNone(tokens[0].last_used_at)

        # organizations cannot login
        response = self.login("o1", "abc123", success=False)

        self.assertEqual(u1.auth_tokens.order_by("-created_at").count(), 1)
        self.assertEqual(o1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertEqual(t1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertEqual(response.json(), {"code": "api_error", "message": "API Error"})

        # teams cannot login
        response = self.login("t1", "abc123", success=False)

        self.assertEqual(u1.auth_tokens.order_by("-created_at").count(), 1)
        self.assertEqual(o1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertEqual(t1.auth_tokens.order_by("-created_at").count(), 0)
        self.assertEqual(response.json(), {"code": "api_error", "message": "API Error"})
