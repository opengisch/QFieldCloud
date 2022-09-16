from allauth.account.auth_backends import (
    AuthenticationBackend as AllAuthAuthenticationBackend,
)


class AuthenticationBackend(AllAuthAuthenticationBackend):
    """Extend the original `allauth` authentication backend to limit user types who can sign in.

    Sign in via team or organization should be forbidden.
    """

    def _authenticate_by_username(self, **credentials):
        user = super()._authenticate_by_username(**credentials)

        if user and user.is_person:
            return user

        return None

    def _authenticate_by_email(self, **credentials):
        user = super()._authenticate_by_email(**credentials)

        if user and user.is_person:
            return user

        return None
