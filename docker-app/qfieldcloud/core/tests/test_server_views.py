from django.core.cache import cache
from django.templatetags.static import static
from django.test import override_settings
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.whitelabel import get_whitelabel_settings


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        # Clear the cache before each test to prevent cached responses
        cache.clear()
        self.whitelabel_settings = get_whitelabel_settings()
        super().setUp()

    def test_server_info_default_settings(self):
        """Test that the endpoint returns the correct default whitelabel settings"""
        response = self.client.get("/api/v1/server/info/")
        data = response.json()

        self.assertTrue("whitelabel" in data)

        system_info = data["whitelabel"]

        # Check title
        self.assertEqual(
            system_info["site_title"], self.whitelabel_settings["site_title"]
        )

        # Check that the URLs have been transformed to absolute URLs properly
        self.assertTrue(system_info["logo_navbar"].startswith("http"))
        self.assertTrue(
            system_info["logo_navbar"].endswith(
                static(self.whitelabel_settings["logo_navbar"])
            )
        )

        self.assertTrue(system_info["logo_main"].startswith("http"))
        self.assertTrue(
            system_info["logo_main"].endswith(
                static(self.whitelabel_settings["logo_main"])
            )
        )

        self.assertTrue(system_info["favicon"].startswith("http"))
        self.assertTrue(
            system_info["favicon"].endswith(static(self.whitelabel_settings["favicon"]))
        )

    @override_settings(
        WHITELABEL={
            "site_title": "My Custom Title",
        }
    )
    def test_server_info_custom_whitelabel_settings(self):
        """Test that the endpoint correctly reflects custom WHITELABEL settings from settings.py"""
        response = self.client.get("/api/v1/server/info/")
        data = response.json()

        self.assertTrue("whitelabel" in data)

        system_info = data["whitelabel"]

        self.assertEqual(system_info["site_title"], "My Custom Title")

    def test_server_info_signup_url_open(self):
        """
        Test that signup_url is an absolute URL to the signup page when signup is open.
        By default, the adapter is open to signup.
        """
        response = self.client.get("/api/v1/server/info/")
        data = response.json()

        self.assertIn("signup_url", data)

        signup_url = data["signup_url"]
        self.assertIsNotNone(signup_url)
        self.assertEqual(signup_url, "http://testserver/accounts/signup/")

    @override_settings(
        ACCOUNT_ADAPTER="qfieldcloud.core.adapters.AccountAdapterSignUpClosed"
    )
    def test_server_info_signup_url_closed(self):
        """Test that signup_url is null when signup is closed"""
        response = self.client.get("/api/v1/server/info/")
        data = response.json()

        self.assertIn("signup_url", data)
        self.assertIsNone(data["signup_url"])
