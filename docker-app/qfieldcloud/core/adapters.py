import logging
import traceback

from allauth.account import app_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailConfirmationHMAC
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from invitations.adapters import BaseInvitationsAdapter

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


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom SocialAccountAdapter to aid SSO integration in QFC.

    Logs stack trace and error details on 3rd party authentication errors.
    """

    def on_authentication_error(
        self,
        request: HttpRequest,
        provider: OAuth2Provider,
        error: str = None,
        exception: Exception = None,
        extra_context: dict = None,
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
