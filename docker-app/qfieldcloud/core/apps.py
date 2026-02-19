from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "qfieldcloud.core"

    def ready(self):
        from qfieldcloud.core import signals  # noqa

        # patch allauth's filter_users_by_email to only return users of type PERSON,
        # as QFC SSO doesn't support ORGANIZATION users.
        from allauth.account import utils as allauth_utils
        from allauth.account import forms as allauth_forms
        from allauth.account import auth_backends as allauth_auth_backends
        from allauth.socialaccount import models as allauth_socialaccount_models

        orig_filter_users_by_email = allauth_utils.filter_users_by_email

        def patched_filter_users_by_email(email, is_active=None, prefer_verified=False):
            from qfieldcloud.core.models import User

            users = orig_filter_users_by_email(
                email, is_active=is_active, prefer_verified=prefer_verified
            )
            person_users = list(filter(lambda u: u.type == User.Type.PERSON, users))

            return person_users

        allauth_utils.filter_users_by_email = patched_filter_users_by_email
        allauth_forms.filter_users_by_email = patched_filter_users_by_email
        allauth_auth_backends.filter_users_by_email = patched_filter_users_by_email
        allauth_socialaccount_models.filter_users_by_email = (
            patched_filter_users_by_email
        )
