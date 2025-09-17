from typing import cast

from allauth.account.auth_backends import (
    AuthenticationBackend as AllAuthAuthenticationBackend,
)
from django.contrib.auth import get_user_model

from qfieldcloud.core.models import Person


class AuthenticationBackend(AllAuthAuthenticationBackend):
    """Extend the original `allauth` authentication backend to limit user types who can sign in.

    Sign in via team or organization should be forbidden.
    """

    def _authenticate_by_username(self, *args, **kwargs) -> Person | None:
        user = super()._authenticate_by_username(*args, **kwargs)

        if user and user.is_person:
            return user

        return None

    def _authenticate_by_email(self, *args, **kwargs) -> Person | None:
        user = super()._authenticate_by_email(*args, **kwargs)

        if user and user.is_person:
            return user

        return None

    def get_user(self, user_id: int) -> Person | None:
        """Almost the same as `contrib.auth.backends.ModelBackend`, but not using the default manager, but the normal `objects` manager

        Returns:
            In theory it can return any of `Person` | `Organization` | `Team` | `None` types, however it will always be a `Person` or `None`
        """
        UserModel = get_user_model()

        try:
            user = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None

        if self.user_can_authenticate(user):
            return cast(Person, user)

        return None
