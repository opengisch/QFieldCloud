import logging

import requests_mock
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from allauth.socialaccount.providers.oauth2.views import OAuth2Adapter
from django.http import HttpRequest
from django.test import override_settings
from rest_framework.test import APITestCase

from qfieldcloud.authentication.views import ListProvidersView

logging.disable(logging.CRITICAL)

KC_REALM_URL = "https://keycloak:7777/realms/myrealm"
KC_TOKEN_URL = f"{KC_REALM_URL}/protocol/openid-connect/token"
KC_AUTH_URL = f"{KC_REALM_URL}/protocol/openid-connect/auth"
KC_OIDC_CONFIG_URL = f"{KC_REALM_URL}/.well-known/openid-configuration"

OPENID_CONNECT_SETTINGS = {
    "issuer": KC_REALM_URL,
    "authorization_endpoint": KC_AUTH_URL,
    "token_endpoint": KC_TOKEN_URL,
}


class FakeAdapter(OAuth2Adapter):
    access_token_url = "http://example.org/token"
    authorize_url = "http://example.org/auth"


class FakeSocialApp(SocialApp):
    pass


class FakeProvider(OAuth2Provider):
    id = "fake"
    name = "Fake"
    uses_apps = False

    oauth2_adapter_class = FakeAdapter

    def get_scope(self):
        return ["scopeA", "scopeB"]


IDP_KEYCLOAK = {
    "OAUTH_PKCE_ENABLED": True,
    "APP": {
        "provider_id": "keycloak",
        "name": "My Keycloak Server",
        "client_id": "keycloak-client-id",
        "secret": "MUST-REMAIN-SECRET",
        "settings": {
            "server_url": KC_OIDC_CONFIG_URL,
        },
    },
}

TESTING_PROVIDERS = {
    "openid_connect": IDP_KEYCLOAK,
}


@override_settings(SOCIALACCOUNT_PROVIDERS={})
class QfcTestCase(APITestCase):
    def setUp(self):
        self.mock_oidc_requests()

    def mock_oidc_requests(self):
        """Mock requests to OIDC configuration endpoint.

        For OpenID Connect providers, configuration settings like the token URL
        and authorization URL are fetched dynamically from the provider's OIDC
        configuration endpoint (`.well-known/openid-configuration`).

        We therefore mock responses to requests like these to provide our own
        settings in tests, and avoid making real requests.
        """
        self.mocked_requests = requests_mock.Mocker()
        self.mocked_requests.start()
        self.addCleanup(self.mocked_requests.stop)

        self.mocked_requests.get(
            KC_OIDC_CONFIG_URL,
            json=OPENID_CONNECT_SETTINGS,
        )

    def fake_provider(self):
        request = HttpRequest()
        provider = FakeProvider(request, app=FakeSocialApp())
        return provider, request

    def list_providers(self):
        response = self.client.get("/api/v1/auth/providers/")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def strip_hash(self, url):
        """Strips asset hash from static file URL."""
        parts = url.split(".")
        return ".".join(parts[:-2] + [parts[-1]])

    def test_lists_password_login_by_default(self):
        providers = self.list_providers()
        expected = [
            {
                "type": "credentials",
                "id": "credentials",
                "name": "Username / Password",
            },
        ]
        self.assertEqual(providers, expected)

    def test_password_login_can_be_disabled(self):
        with self.settings(QFIELDCLOUD_PASSWORD_LOGIN_IS_ENABLED=False):
            providers = self.list_providers()

        self.assertEqual(providers, [])

    @override_settings(SOCIALACCOUNT_PROVIDERS=TESTING_PROVIDERS)
    def test_lists_configured_social_providers(self):
        providers = self.list_providers()
        expected = [
            {
                "type": "credentials",
                "id": "credentials",
                "name": "Username / Password",
            },
            {
                "type": "oauth2",
                "id": "keycloak",
                "name": "My Keycloak Server",
                "grant_flow": 3,
                "scope": "openid profile email",
                "pkce_enabled": True,
                "token_url": KC_TOKEN_URL,
                "refresh_token_url": KC_TOKEN_URL,
                "request_url": KC_AUTH_URL,
                "redirect_host": "localhost",
                "redirect_port": 7070,
                "redirect_url": "",
                "client_id": "keycloak-client-id",
                "extra_tokens": {"id_token": "X-QFC-ID-Token"},
                "styles": {},
            },
        ]
        providers[-1]["styles"] = {}
        self.assertEqual(providers, expected)

    @override_settings(SOCIALACCOUNT_PROVIDERS=TESTING_PROVIDERS)
    def test_client_secret_is_not_disclosed(self):
        providers = self.list_providers()

        client_id = IDP_KEYCLOAK["APP"]["client_id"]
        secret = IDP_KEYCLOAK["APP"]["secret"]
        self.assertIn(client_id, str(providers))
        self.assertNotIn(secret, str(providers))

    def test_always_adds_openid_scope(self):
        provider, request = self.fake_provider()

        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["scope"], "openid scopeA scopeB")

    def test_supports_subproviders(self):
        provider, request = self.fake_provider()

        # Generic provider
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["id"], "fake")

        # Subprovider
        provider.uses_apps = True
        provider.app.provider_id = "fake_subprovider"

        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["id"], "fake_subprovider")

    def test_correctly_determines_grant_flow(self):
        provider, request = self.fake_provider()

        # PKCE disabled -> Authorization Code
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(
            provider_data["grant_flow"], ListProvidersView.FLOW_AUTHORIZATION_CODE
        )

        # PKCE enabled -> Authorization Code with PKCE
        provider.pkce_enabled_default = True
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(
            provider_data["grant_flow"], ListProvidersView.FLOW_AUTHORIZATION_CODE_PKCE
        )

    def test_correctly_detects_all_methods_to_enable_pkce(self):
        provider, request = self.fake_provider()

        # PKCE disabled (default)
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["pkce_enabled"], False)

        # Provider wide setting
        conf = {"fake": {"OAUTH_PKCE_ENABLED": True}}
        with self.settings(SOCIALACCOUNT_PROVIDERS=conf):
            provider_data = ListProvidersView().get_provider_data(provider, request)

        self.assertEqual(provider_data["pkce_enabled"], True)

        # App setting
        provider.app.settings["oauth_pkce_enabled"] = True
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["pkce_enabled"], True)
        provider.app.settings.pop("oauth_pkce_enabled")

        # Provider default
        provider.pkce_enabled_default = True
        provider_data = ListProvidersView().get_provider_data(provider, request)
        self.assertEqual(provider_data["pkce_enabled"], True)

    @override_settings(SOCIALACCOUNT_PROVIDERS=TESTING_PROVIDERS)
    def test_includes_provider_styles(self):
        providers = self.list_providers()

        keycloak = providers[-1]
        for key in list(keycloak):
            if key not in ("id", "type", "styles"):
                keycloak.pop(key)

        for theme in ["light", "dark"]:
            # Strip asset hash
            styles = keycloak["styles"][theme]
            styles["logo"] = self.strip_hash(styles["logo"])

        expected = {
            "type": "oauth2",
            "id": "keycloak",
            # ...
            "styles": {
                "required": False,
                "light": {
                    "logo": "http://testserver/staticfiles/sso/keycloak.svg",
                    "color_fill": "#FFFFFF",
                    "color_stroke": "#747775",
                    "color_text": "#1F1F1F",
                },
                "dark": {
                    "logo": "http://testserver/staticfiles/sso/keycloak.svg",
                    "color_fill": "#131314",
                    "color_stroke": "#8E918F",
                    "color_text": "#E3E3E3",
                },
            },
        }
        self.assertEqual(keycloak, expected)
