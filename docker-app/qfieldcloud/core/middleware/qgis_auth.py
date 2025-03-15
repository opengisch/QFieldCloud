import logging

import jwt
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login

logger = logging.getLogger(__name__)


class QGISAuthenticationMiddleware:
    """Authentication middleware for OIDC authentication using QGIS.

    This middleware allows to authenticate a user based on an OIDC ID token
    that is passed in a custom HTTP header.

    If a QGIS auth config is set up to pass the `id_token` in that header, and
    has the proper OpenID Connect scopes configured, this allows to authenticate
    to QFC using an OIDC flow performed in QGIS.

    This middleware MUST be listed after these:

    - django.contrib.auth.middleware.AuthenticationMiddleware
    - allauth.account.middleware.AccountMiddleware
    - django.contrib.messages.middleware.MessageMiddleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # User already has a session
            return self.get_response(request)

        id_token = self.get_id_token(request)
        access_token = self.get_access_token(request)

        if not any([id_token, access_token]):
            # No tokens found, nothing for us to do
            return self.get_response(request)

        provider = self.get_provider(request, id_token, access_token)
        if not provider:
            # Could not determine the provider, bail
            return self.get_response(request)

        class Token:
            def __init__(self, token):
                self.token = token

        token_response = {}
        if id_token:
            token_response["id_token"] = id_token
        token = Token(access_token)

        oauth_adapter = provider.get_oauth2_adapter(request)
        social_login = oauth_adapter.complete_login(
            request, provider.app, token, response=token_response
        )
        complete_social_login(request, social_login)
        response = self.get_response(request)

        logger.info("Authenticated user: %s" % request.user)
        return response

    def get_id_token(self, request):
        return request.headers.get("X-QFC-ID-Token")

    def get_access_token(self, request):
        auth_header = request.headers.get("Authorization")

        if not (auth_header and auth_header.startswith("Bearer ")):
            return

        access_token = auth_header.split(" ")[1]
        return access_token

    def get_provider(self, request, id_token, access_token):
        idp_id = request.headers.get("X-QFC-IDP-ID")

        if not idp_id and id_token:
            idp_id = self.infer_idp_from_id_token(request, id_token)

        if not idp_id and access_token:
            idp_id = self.infer_idp_from_access_token(request, access_token)

        # TODO: Currently we default to Google if no IDP is explicitly set
        # in the HTTP headers. We might want a configurable default provider.
        if not idp_id:
            idp_id = "google"

        social_account_adapter = get_adapter(request)

        providers = social_account_adapter.list_providers(request)
        if not providers:
            return None

        provider = social_account_adapter.get_provider(request, idp_id)
        return provider

    def infer_idp_from_id_token(self, request, id_token):
        try:
            decoded = jwt.decode(id_token, options={"verify_signature": False})
        except Exception:
            return

        aud = decoded.get("aud")
        social_account_adapter = get_adapter(request)

        apps = social_account_adapter.list_apps(request)
        for app in apps:
            if app.client_id == aud:
                return app.provider_id

    def infer_idp_from_access_token(self, request, access_token):
        try:
            decoded = jwt.decode(access_token, options={"verify_signature": False})
        except Exception:
            return

        azp = decoded.get("azp")
        social_account_adapter = get_adapter(request)

        apps = social_account_adapter.list_apps(request)
        for app in apps:
            if app.client_id == azp:
                return app.provider_id
