import logging
import traceback

from allauth.account import app_settings
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.exceptions import ValidationError
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


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom SocialAccountAdapter to aid SSO integration in QFC.

    Logs stack trace and error details on 3rd party authentication errors.
    """

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):
        logger.error("SSO Authentication error:", exc_info=True)
        logger.error(f"Provider: {provider!r}")
        logger.error(f"Error: {error!r}")

        # Make stack strace available in template context.
        extra_context["formatted_exception"] = "\n".join(
            traceback.format_exception(exception)
        )
        return super().on_authentication_error(
            request, provider, error, exception, extra_context
        )
