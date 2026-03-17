from typing import Optional

from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.providers.base import Provider
from allauth.socialaccount.providers.oauth2.views import OAuth2Adapter
from django.conf import settings
from django.http import HttpRequest

from qfieldcloud.authentication.sso.provider_styles import SSOProviderStyles

# These values are tied to the `GrantFlow` enum in QGIS:
# oauth2/core/qgsauthoauth2config.h: QgsAuthOAuth2Config::GrantFlow
FLOW_AUTHORIZATION_CODE = 0
FLOW_AUTHORIZATION_CODE_PKCE = 3

# Address at which QGIS should spawn its temporary webserver to catch
# the redirect. These mostly happen to match QGIS defaults, except we use
# localhost instead of 127.0.0.1 because many OAuth2 apps don't allow IPs.
QGIS_REDIRECT_HOST = "localhost"
QGIS_REDIRECT_PORT = 7070
QGIS_REDIRECT_URL = ""


def get_credentials_provider() -> dict:
    return {
        "type": "credentials",
        "id": "credentials",
        "name": "Username / Password",
    }


def get_oauth2_provider(
    provider: Provider,
    oauth2_adapter: OAuth2Adapter,
    request: Optional[HttpRequest] = None,
) -> dict:
    provider_id = getattr(provider, "sub_id", provider.id)

    # Allow styles to be pre-attached to the provider (used in serializers) or fetched via request (used in views)
    styles = getattr(provider, "styles", None)
    if styles is None and request is not None:
        styles = SSOProviderStyles(request).get(provider_id)

    return {
        "type": "oauth2",
        "id": provider_id,
        "name": provider.name,
        "grant_flow": get_flow_type(provider),
        "scope": get_scope(provider, oauth2_adapter),
        "pkce_enabled": is_pkce_enabled(provider),
        "token_url": oauth2_adapter.access_token_url,
        "refresh_token_url": oauth2_adapter.access_token_url,
        "request_url": oauth2_adapter.authorize_url,
        "redirect_host": QGIS_REDIRECT_HOST,
        "redirect_port": QGIS_REDIRECT_PORT,
        "redirect_url": QGIS_REDIRECT_URL,
        "client_id": provider.app.client_id,
        "extra_tokens": {"id_token": settings.QFIELDCLOUD_ID_TOKEN_HEADER_NAME},
        "idp_id_header": settings.QFIELDCLOUD_IDP_ID_HEADER_NAME,
        "styles": styles,
    }


def get_scope(provider: Provider, oauth2_adapter: OAuth2Adapter) -> str:
    scope = provider.get_scope()
    if "openid" not in scope:
        scope.insert(0, "openid")

    return oauth2_adapter.scope_delimiter.join(scope)


def is_pkce_enabled(provider: Provider) -> bool:
    pkce_enabled = provider.app.settings.get("oauth_pkce_enabled")
    if pkce_enabled is None:
        pkce_enabled = provider.get_settings().get(
            "OAUTH_PKCE_ENABLED",
            provider.pkce_enabled_default,
        )

    return pkce_enabled


def get_flow_type(provider: Provider) -> int:
    if is_pkce_enabled(provider):
        return FLOW_AUTHORIZATION_CODE_PKCE

    return FLOW_AUTHORIZATION_CODE


def get_all_auth_providers(request: HttpRequest) -> list[dict]:
    """Generates the full list of formatted auth providers."""
    auth_providers = []

    if settings.QFIELDCLOUD_PASSWORD_LOGIN_IS_ENABLED:
        auth_providers.append(get_credentials_provider())

    social_account_adapter = get_adapter(request)
    for provider in social_account_adapter.list_providers(request):
        if hasattr(provider, "get_oauth2_adapter"):
            oauth2_adapter = provider.get_oauth2_adapter(request)
            auth_providers.append(
                get_oauth2_provider(provider, oauth2_adapter, request)
            )

    return auth_providers
