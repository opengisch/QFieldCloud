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
        system_info = data["system"]

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
        system_info = data["system"]

        self.assertEqual(system_info["site_title"], "My Custom Title")
