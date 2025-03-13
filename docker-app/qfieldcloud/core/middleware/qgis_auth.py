import logging

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

        provider = self.get_provider(request)
        if not provider:
            # Could not determine the provider, bail
            return self.get_response(request)

        if id_token:
            userinfo = self.authenticate_with_id_token(request, provider, id_token)
        else:
            # This is a fallback to authenticate using the OAuth2 access token,
            # instead of the OIDC ID token. This can be removed once a QGIS
            # version containing https://github.com/qgis/QGIS/pull/60668 is
            # used on all the relevant devices.
            userinfo = self.authenticate_with_access_token(
                request, provider, access_token
            )

        if not userinfo:
            return self.get_response(request)

        # Delegate to django-allauth's social login flow.
        # This will authenticate the user, and:
        # - Re-use an existing session, if one exists
        # - Otherwise log the user in, and create a session, if the user exists
        # - Sign up a new user, if the user does not exist
        social_login = provider.sociallogin_from_response(request, userinfo)
        complete_social_login(request, social_login)
        response = self.get_response(request)

        logger.info("Authenticated user: %s" % request.user)
        return response

    def authenticate_with_id_token(self, request, provider, id_token):
        """Authenticate using an OpenID Connect ID token.

        This is the preferred way to authenticate, and should be used when
        possible. An ID token contains all the information needed for us to
        perform authentication (instead of authorization) of the user, without
        the need to do a request to the IDP's `userinfo` endpoint.
        """
        oauth_adapter = provider.oauth2_adapter_class(request)
        userinfo = oauth_adapter._decode_id_token(provider.app, id_token)

        logger.info("Authenticating using OIDC ID token")
        return userinfo

    def authenticate_with_access_token(self, request, provider, access_token):
        """Authenticate using an OAuth2 access token.

        This is a fallback to authenticate using the OAuth2 access token,
        and should be removed once we have a recent enough QGIS version to use
        ID tokens everywhere.

        This will depend on the IDP having a `userinfo` endpoint, and will
        issue a request to that endpoint every time a user is authenticated.
        """
        oauth_adapter = provider.oauth2_adapter_class(request)
        userinfo = oauth_adapter._fetch_user_info(access_token)

        logger.info("Authenticating using OAuth2 Access Token")
        return userinfo

    def get_id_token(self, request):
        return request.headers.get("X-QFC-ID-Token")

    def get_access_token(self, request):
        auth_header = request.headers.get("Authorization")

        if not (auth_header and auth_header.startswith("Bearer ")):
            return

        access_token = auth_header.split(" ")[1]
        return access_token

    def get_provider(self, request):
        idp_id = request.headers.get("X-QFC-IDP-ID")

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
