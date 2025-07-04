import logging
import traceback
from random import randint
from typing import Literal

from allauth.account import app_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailConfirmationHMAC
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from invitations.adapters import BaseInvitationsAdapter

from qfieldcloud.authentication.sso.provider_styles import SSOProviderStyles
from qfieldcloud.core.models import Person

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter, BaseInvitationsAdapter):
    """Custom account adapter, inheriting the invitations adapter.

    NOTE Unfortunately there is no way to setup the User model for allauth,
    except changing it globally for everyone. Therefore this adapter tries
    to overcome this limitation by providing custom `new_user` method.
    """

    def new_user(self, request):
        """
        Instantiates a new User instance.
        """
        user = Person()
        return user

    def clean_username(self, username, shallow=False):
        result = super().clean_username(username, shallow)

        # NOTE `allauth` depends on the `PRESERVE_USERNAME_CASING` to make `iexact` lookups.
        # When set to `False` as it is now, all `Person` usernames are stored as lowercase.
        # However, usernames for `Organization` or `Team` are not stored lowercase and then `allauth` does not check for them.

        # TODO check what are the consequences if we don't add all of these and change the `PRESERVE_USERNAME_CASING` to `True`.
        if not app_settings.PRESERVE_USERNAME_CASING:
            username_field = app_settings.USER_MODEL_USERNAME_FIELD

            if Person.objects.filter(
                **{f"{username_field}__iexact": username},
            ).exists():
                error_message = Person._meta.get_field(
                    username_field
                ).error_messages.get("unique")

                if not error_message:
                    error_message = self.error_messages["username_taken"]

                raise ValidationError(
                    error_message,
                    params={
                        "model_name": Person.__name__,
                        "field_label": username_field,
                    },
                )

        return result

    def populate_username(self, request: HttpRequest, user: AbstractUser) -> None:
        """Customize username population for signups via social logins.

        When a user signs up via username and password, we try to respect their
        choice of username, and just delegate to the default implementation to
        avoid collisions.

        For users that directly sign up via a social login however, we:
        - Take the local part of their email (part before the '@' sign)
        - Append a random 4-digit suffix to make it likely to be unique and
          not communicate any information about the existence of other users
        - Let generate_unique_username() normalize the username and ensure its
          uniqueness.
        """

        from allauth.account.utils import user_email, user_username

        email = user_email(user)
        username = user_username(user)

        if username:
            # Manually chosen username - defer to default implementation
            return super().populate_username(request, user)

        # Signup via social login - automatically generate a unique username
        localpart = email.split("@")[0]
        suffix = str(randint(1000, 9999))
        username_candidate = f"{localpart}{suffix}"

        if app_settings.USER_MODEL_USERNAME_FIELD:
            user_username(
                user,
                self.generate_unique_username(
                    [username_candidate], regex=r"[^\w\s\-_]"
                ),
            )

    def send_confirmation_mail(
        self,
        request: HttpRequest,
        email_confirmation: EmailConfirmationHMAC,
        signup: bool,
    ) -> None:
        """
        Overrides allauth's default method for sending a confirmation email.
        Adds the email provided by the future user in the session.
        """
        if request and email_confirmation:
            request.session["account_verified_email"] = (
                email_confirmation.email_address.email
            )

        super().send_confirmation_mail(request, email_confirmation, signup)


class AccountAdapterSignUpOpen(AccountAdapter):
    """Account adapter for open signup.

    This adapter is used when the signup is open, i.e. when users can register themselves.
    """

    def is_open_for_signup(self, request: HttpRequest) -> Literal[True]:
        return True


class AccountAdapterSignUpClosed(AccountAdapter):
    """Account adapter for closed signup.

    This adapter is used when the signup is closed, i.e. when users cannot register themselves.
    A user can still be added via Django admin.
    """

    def is_open_for_signup(self, request: HttpRequest) -> Literal[False]:
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom SocialAccountAdapter to aid SSO integration in QFC.

    Logs stack trace and error details on 3rd party authentication errors.
    """

    def on_authentication_error(
        self,
        request: HttpRequest,
        provider: OAuth2Provider,
        error: str | None = None,
        exception: Exception | None = None,
        extra_context: dict | None = None,
    ) -> None:
        logger.error("SSO Authentication error:", exc_info=True)
        logger.error(f"Provider: {provider!r}")
        logger.error(f"Error: {error!r}")

        if not extra_context:
            extra_context = {}

        # Make stack strace available in template context.
        #
        # That way, it could be displayed in the frontend (for debugging
        # purposes), by overriding socialaccount/authentication_error.html and
        # using {{ formatted_exception }} to display the stack trace.
        extra_context["formatted_exception"] = "\n".join(
            traceback.format_exception(exception)
        )
        super().on_authentication_error(
            request, provider, error, exception, extra_context
        )

    def list_providers(self, request: HttpRequest) -> list:
        """Extend providers with styling information.

        This adds a `styles` dictionary to each provider, which contains
        the styling information for that provider from the
        QFIELDCLOUD_SSO_PROVIDER_STYLES settings.
        """

        providers = super().list_providers(request)

        for provider in providers:
            provider.styles = SSOProviderStyles(request).get(provider.sub_id)

        return providers
