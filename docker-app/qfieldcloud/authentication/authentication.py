from typing import Type

from django.contrib.auth import get_user_model
from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import exceptions
from rest_framework.authentication import (
    TokenAuthentication as DjangoRestFrameworkTokenAuthentication,
)

from .models import AuthToken

User = get_user_model()


def invalidate_all_tokens(user: User) -> int:
    now = timezone.now()
    return AuthToken.objects.filter(user=user, expires_at__gt=now).update(
        expires_at=now
    )


def create_token(
    token_model: Type[AuthToken],
    user: User,
    _serializer=None,
    request: HttpRequest = None,
) -> AuthToken:
    user_agent = ""
    client_type = AuthToken.ClientType.UNKNOWN

    if request:
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        client_type = AuthToken.guess_client_type(user_agent)

    token = token_model.objects.create(
        user=user, client_type=client_type, user_agent=user_agent
    )

    return token


class TokenAuthentication(DjangoRestFrameworkTokenAuthentication):
    """
    Multi token authentication based on simple token based authentication.
    Clients should authenticate by passing the token key in the "Authorization"
    HTTP header, prepended with the string "Token ".  For example:
        Authorization: Token 401f7ac837da42b97f613d789819ff93537bee6a
    """

    model = AuthToken

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.get(key=key)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(_("Invalid token."))

        if not token.is_active:
            raise exceptions.AuthenticationFailed(_("Token has expired."))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_("User inactive or deleted."))

        # update the token last used time
        # NOTE the UPDATE may be performed already on the `token = model.objects.get(key=key)`, but we lose "token has expired" exception.
        token.last_used_at = timezone.now()
        token.save()

        return (token.user, token)
