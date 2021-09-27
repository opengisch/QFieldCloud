from datetime import datetime

from django.utils import timezone
from django.utils.translation import gettext as _
from qfieldcloud.core.models import AuthToken, User
from rest_framework import exceptions
from rest_framework.authentication import (
    TokenAuthentication as DjangoRestFrameworkTokenAuthentication,
)


def invalidate_all_tokens(user: User) -> int:
    now = timezone.now()
    return AuthToken.objects.filter(user=user, expires_at__gt=now).update(
        expires_at=now
    )


class TokenAuthentication(DjangoRestFrameworkTokenAuthentication):
    """
    Multi toke authentication based on simple token based authentication.
    Clients should authenticate by passing the token key in the "Authorization"
    HTTP header, prepended with the string "Token ".  For example:
        Authorization: Token 401f7ac837da42b97f613d789819ff93537bee6a
    """

    model = AuthToken

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related("user").get(key=key)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(_("Invalid token."))

        if not token.is_active:
            raise exceptions.AuthenticationFailed(_("Token has expired."))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_("User inactive or deleted."))

        # update the token last used time
        # NOTE the UPDATE may be performed already on the `token = model.objects.get(key=key)`, but we lose "token has expired" exception.
        token.updated_at = datetime.now()
        token.save()

        return (token.user, token)
