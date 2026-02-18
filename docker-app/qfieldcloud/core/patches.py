def patch_allauth_email_filter():
    """Patch allauth's filter_users_by_email only return users of type PERSON.

    This is to prevent django-allauth picking an organization with a matching
    email address when someone signs up via social login. Because `Organization`
    objects also inherit from `AbstractUser`, and may exist with the same email
    address as the user that created them, allauth may pick the organization
    instead of the `Person` when linking the social account to an existing user.

    We therefore patch `filter_users_by_email` here to filter out any results
    that are not of type `Person`.
    """

    from typing import Optional

    from allauth.account import auth_backends as allauth_auth_backends
    from allauth.account import forms as allauth_forms
    from allauth.account import utils as allauth_utils
    from allauth.socialaccount import models as allauth_socialaccount_models

    orig_filter_users_by_email = allauth_utils.filter_users_by_email

    def patched_filter_users_by_email(
        email, is_active: Optional[bool] = None, prefer_verified: bool = False
    ):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        users = orig_filter_users_by_email(
            email, is_active=is_active, prefer_verified=prefer_verified
        )
        person_users = list(filter(lambda u: u.type == User.Type.PERSON, users))

        return person_users

    allauth_utils.filter_users_by_email = patched_filter_users_by_email
    allauth_forms.filter_users_by_email = patched_filter_users_by_email
    allauth_auth_backends.filter_users_by_email = patched_filter_users_by_email
    allauth_socialaccount_models.filter_users_by_email = patched_filter_users_by_email
