from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.authentication import (
    TokenAuthentication as DjangoRestFrameworkTokenAuthentication,
)

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.exceptions import AuthenticationViaTokenFailedError
from qfieldcloud.core.models import User, WorkerPool

# How often the last time a worker pool was seen is stored.
LAST_SEEN_UPDATE_INTERVAL = timedelta(minutes=1)


def invalidate_all_tokens(user: User) -> int:
    now = timezone.now()
    return AuthToken.objects.filter(user=user, expires_at__gt=now).update(
        expires_at=now
    )


def create_token(
    token_model: type[AuthToken],
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
    """Multi token authentication based on simple token based authentication.

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


class WorkerPoolAuthentication(DjangoRestFrameworkTokenAuthentication):
    """Authenticates a worker with its pool's credential, the pool is available as `request.auth`.

    Workers pass the credential in the "Authorization" HTTP header, prepended with the string "WorkerPool ".
    """

    keyword = "WorkerPool"

    def authenticate_credentials(self, key):
        try:
            pool = WorkerPool.objects.get(
                credential_hash=WorkerPool.hash_credential(key)
            )
        except WorkerPool.DoesNotExist:
            raise AuthenticationViaTokenFailedError(_("Invalid token."))

        # NOTE idle workers call every few seconds, writing once per interval is enough to tell they are alive
        now = timezone.now()
        WorkerPool.objects.filter(pk=pool.pk).filter(
            Q(last_seen_at__isnull=True)
            | Q(last_seen_at__lt=now - LAST_SEEN_UPDATE_INTERVAL)
        ).update(last_seen_at=now)

        return (AnonymousUser(), pool)
