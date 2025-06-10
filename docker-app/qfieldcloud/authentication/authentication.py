from typing import Type

from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.authentication import (
    TokenAuthentication as DjangoRestFrameworkTokenAuthentication,
)

from qfieldcloud.core.models import User

from ..core.exceptions import AuthenticationViaTokenFailedError
from .models import AuthToken


def invalidate_all_tokens(user: User) -> int:
    now = timezone.now()
    return AuthToken.objects.filter(user=user, expires_at__gt=now).update(
        expires_at=now
    )


def create_token(
    token_model: Type[AuthToken],
    user: User,
    _serializer=None,
    request: HttpRequest | None = None,
) -> AuthToken:
    user_agent = ""
    client_type = AuthToken.ClientType.UNKNOWN

    if request:
        user_agent = request.headers.get("user-agent", "")
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
            raise AuthenticationViaTokenFailedError(_("Invalid token."))

        if not token.is_active:
            raise AuthenticationViaTokenFailedError(_("Token has expired."))

        if not token.user.is_active:
            raise AuthenticationViaTokenFailedError(_("User inactive or deleted."))

        # update the token last used time
        # NOTE the UPDATE may be performed already on the `token = model.objects.get(key=key)`, but we lose "token has expired" exception.
        token.last_used_at = timezone.now()
        token.save()

        return (token.user, token)
