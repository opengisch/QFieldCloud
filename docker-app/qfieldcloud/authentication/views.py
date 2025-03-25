from allauth.socialaccount.adapter import get_adapter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import status
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import create_token
from .models import AuthToken
from .utils import load_module

LoginSerializer = load_module(settings.QFIELDCLOUD_LOGIN_SERIALIZER)
TokenSerializer = load_module(settings.QFIELDCLOUD_TOKEN_SERIALIZER)
UserSerializer = load_module(settings.QFIELDCLOUD_USER_SERIALIZER)

sensitive_post_parameters_m = method_decorator(
    sensitive_post_parameters(
        "password", "old_password", "new_password1", "new_password2"
    )
)


class LoginView(ObtainAuthToken):
    """Create a new user session.

    Check the credentials and return the REST Token if the credentials are valid and authenticated.
    Accept the following POST parameters: username OR email, password
    Return information about the token and the user.
    """

    # Based on: https://github.com/Tivix/django-rest-auth/blob/master/rest_auth/views.py#L33

    permission_classes = (AllowAny,)
    serializer_class = LoginSerializer
    token_model = AuthToken

    @sensitive_post_parameters_m
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.request = request
        self.serializer = self.get_serializer(
            data=self.request.data, context={"request": request}
        )
        self.serializer.is_valid(raise_exception=True)
        validated_data = self.serializer.validated_data
        assert validated_data and "user" in validated_data
        self.token = create_token(
            self.token_model, validated_data["user"], self.serializer, self.request
        )

        serializer = TokenSerializer(
            instance=self.token, context={"request": self.request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Invalidate the user session.

    Calls Django logout method and invalidate the Token object assigned to the current User object.
    Accepts nothing, returns a details message.
    """

    # Based on: https://github.com/Tivix/django-rest-auth/blob/master/rest_auth/views.py#L109

    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        if getattr(settings, "ACCOUNT_LOGOUT_ON_GET", False):
            response = self.logout(request)
        else:
            response = self.http_method_not_allowed(request, *args, **kwargs)

        return self.finalize_response(request, response, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.logout(request)

    def logout(self, request):
        try:
            now = timezone.now()
            request.user.auth_tokens.filter(expires_at__gt=now).update(expires_at=now)
        except (AttributeError, ObjectDoesNotExist):
            pass

        response = Response(
            {"detail": _("Successfully logged out.")}, status=status.HTTP_200_OK
        )
        return response


class UserView(RetrieveAPIView):
    """Read user fields.

    Accepts nothing, returns the user fields.
    """

    # Based on: https://github.com/Tivix/django-rest-auth/blob/master/rest_auth/views.py#L146

    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user

    def get_queryset(self):
        """
        Adding this method since it is sometimes called when using
        django-rest-swagger
        https://github.com/Tivix/django-rest-auth/issues/275
        """
        return get_user_model().objects.none()


class ListProvidersView(APIView):
    """Lists the available authentication providers."

    This will mostly be allauth SocialAccount providers, plus the
    username/password login.
    """

    FLOW_AUTHORIZATION_CODE = 0
    FLOW_AUTHORIZATION_CODE_PKCE = 3

    permission_classes = (AllowAny,)

    def is_pkce_enabled(self, provider):
        pkce_enabled = False
        pkce_enabled = provider.app.settings.get("oauth_pkce_enabled")
        if pkce_enabled is None:
            pkce_enabled = provider.get_settings().get(
                "OAUTH_PKCE_ENABLED",
                provider.pkce_enabled_default,
            )

        return pkce_enabled

    def get_flow_type(self, provider):
        if self.is_pkce_enabled(provider):
            return self.FLOW_AUTHORIZATION_CODE_PKCE

        return self.FLOW_AUTHORIZATION_CODE

    def get(self, request, *args, **kwargs):
        data = []

        # TODO: Introduce setting to disable username/password login
        data.append(
            {
                "type": "credentials",
                "id": "credentials",
                "name": "Username / Password",
            }
        )

        social_account_adapter = get_adapter(request)
        providers = social_account_adapter.list_providers(request)

        for provider in providers:
            oauth2_adapter = provider.get_oauth2_adapter(request)

            scope = provider.get_scope()
            if "openid" not in scope:
                scope.insert(0, "openid")
            scope = oauth2_adapter.scope_delimiter.join(scope)

            provider_id = provider.id
            if provider.uses_apps and provider.app.provider_id:
                # Support subproviders like 'keycloak'
                # (which is a subprovider of 'openid_connect')
                provider_id = provider.app.provider_id

            provider_data = {
                "type": "oauth2",
                "id": provider_id,
                "name": provider.name,
                "grant_flow": self.get_flow_type(provider),
                "scope": scope,
                "pkce_enabled": self.is_pkce_enabled(provider),
                "token_url": oauth2_adapter.access_token_url,
                "refresh_token_url": oauth2_adapter.access_token_url,
                "request_url": oauth2_adapter.authorize_url,
                "redirect_host": "localhost",
                "redirect_port": 7070,
                "redirect_url": "",
                "client_id": provider.app.client_id,
                "extra_tokens": {"id_token": "X-QFC-ID-Token"},
            }

            pkce_enabled = self.is_pkce_enabled(provider)
            if not pkce_enabled:
                provider_data["client_secret"] = provider.app.secret

            data.append(provider_data)

        response = Response(data)
        return response
