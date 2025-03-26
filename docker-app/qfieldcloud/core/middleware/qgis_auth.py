import logging

from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialToken
from django.http import HttpRequest

logger = logging.getLogger(__name__)


class QGISAuthenticationMiddleware:
    """Authentication middleware for OIDC authentication using QGIS.

    This middleware allows to authenticate a user based on an OIDC ID token
    that is passed in a custom HTTP header.

    If a QGIS auth config is set up to pass the `id_token` in that header, and
    has the proper OpenID Connect scopes configured, this allows to authenticate
    to QFC using an OIDC flow performed in QGIS.

    Alternatively, an OAuth2 access token (which QGIS passes in the
    `Authorization` header by default) can be used.

    This middleware MUST be listed after these:

    - django.contrib.auth.middleware.AuthenticationMiddleware
    - allauth.account.middleware.AccountMiddleware
    - django.contrib.messages.middleware.MessageMiddleware

    The reason why this middleware is required is this:

    Normally, an OIDC flow using django-allauth's social account functionality
    returns the user to a well defined callback URL, for example
    /accounts/google/login/callback/. This URL is then handled by the callback
    view that extracts the tokens from the request and completes the login.

    QGIS however doesn't do this. It makes no distinction between an initial
    "login request" and any subsequent requests. It just performs the OIDC flow
    with the IDP, gets the access token / ID token, and attaches those to any
    requests that use this auth config in the HTTP headers.

    This middleware therefore looks for those tokens in those headers, extracts
    them, and then delegates the actual authentication to django-allauth. Once
    that succeeds, the user is logged in, a session is created, and the session
    is persisted using the standard mechanisms (e.g. a session cookie).

    On subsequent requests QGIS sends back those session cookies, and
    authentication does not need to be performed again.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        """Detect and extract HTTP headers intended for SSO auth.

        Because this code gets called for *every* single request, we need to
        be quite defensive here. For reasons of performance and robustness.

        We need to abort as early as possible if we can determine that the
        request is not intended for SSO auth. And we must not cause any
        unhandled exceptions that could interfere with normal requests.
        """
        if request.user.is_authenticated:
            # User already has a session
            return self.get_response(request)

        id_token = self.get_id_token(request)
        access_token = self.get_access_token(request)

        if not any([id_token, access_token]):
            # No tokens found, nothing for us to do
            return self.get_response(request)

        # Require QFC clients to send a header to explicitly specify the IDP
        idp_id = request.headers.get("X-QFC-IDP-ID")
        if not idp_id:
            return self.get_response(request)

        provider = self.get_provider(request, idp_id)
        if not provider:
            # Could not determine the provider, bail
            return self.get_response(request)

        # Delegate the actual authentication to django-allauth.
        #
        # We do this by emulating the parameters for django-allauth's
        # OAuth2Adapter.complete_login() method in the way that it expects them.
        #
        # Specifically, a SocialToken instance with the access token, and a
        # `response` dictionary with the ID token (if available).
        token = SocialToken(token=access_token)
        token_response = {}
        if id_token:
            token_response["id_token"] = id_token

        # This verifies the token, determines attributes like 'uid' and 'email',
        # and prepares a SocialLogin instance.
        oauth_adapter = provider.get_oauth2_adapter(request)
        social_login = oauth_adapter.complete_login(
            request, provider.app, token, response=token_response
        )

        # This performs signup of the a user, if necessary, authenticates
        # the user, links the social account, and creates a session.
        complete_social_login(request, social_login)

        logger.info("Authenticated user: %s" % request.user)
        return self.get_response(request)

    def get_id_token(self, request: HttpRequest):
        return request.headers.get("X-QFC-ID-Token")

    def get_access_token(self, request: HttpRequest):
        auth_header = request.headers.get("Authorization")

        if not (auth_header and auth_header.startswith("Bearer ")):
            return None

        access_token = auth_header.split(" ")[1]
        return access_token

    def get_provider(self, request: HttpRequest, idp_id: str):
        social_account_adapter = get_adapter(request)
        providers = social_account_adapter.list_providers(request)
        if not providers:
            return None

        provider = social_account_adapter.get_provider(request, idp_id)
        return provider
