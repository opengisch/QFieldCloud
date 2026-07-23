import logging
from unittest.mock import MagicMock

from allauth.account import app_settings
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialLogin
from allauth.socialaccount.providers.dummy.provider import DummyProvider
from django.test import TestCase, override_settings

from qfieldcloud.core.adapters import SocialAccountAdapter
from qfieldcloud.core.models import Organization, Person, User
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()
        self.dummy_provider = DummyProvider(request=MagicMock(), app=None)

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": True}}
    )
    def test_3rd_party_auth_does_not_link_to_organization(self):
        Organization.objects.create(
            username="the_org",
            organization_owner=Person.objects.create(username="org_owner"),
            email="the_email@qfield.cloud",
        )

        email_address = EmailAddress(email="the_email@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNone(match_result)

    @override_settings(
        ACCOUNT_EMAIL_VERIFICATION=app_settings.EmailVerificationMethod.MANDATORY,
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": True}},
    )
    def test_3rd_party_auth_does_not_link_to_unverified_email_when_verification_mandatory(
        self,
    ):
        Person.objects.create(
            username="the_person",
            email="the_email@qfield.cloud",
        )

        email_address = EmailAddress(email="the_email@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNone(match_result)

    @override_settings(
        ACCOUNT_EMAIL_VERIFICATION=app_settings.EmailVerificationMethod.OPTIONAL,
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": True}},
    )
    def test_3rd_party_auth_links_to_user_with_unverified_email_when_verification_optional(
        self,
    ):
        person = Person.objects.create(
            username="the_person",
            email="the_email@qfield.cloud",
        )

        email_address = EmailAddress(email="the_email@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNotNone(match_result)

        matched_user, matched_email = match_result

        self.assertEqual(matched_user.pk, person.pk)
        self.assertEqual(matched_email, "the_email@qfield.cloud")
        self.assertEqual(matched_user.email, "the_email@qfield.cloud")

    @override_settings(
        ACCOUNT_EMAIL_VERIFICATION=app_settings.EmailVerificationMethod.MANDATORY,
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": True}},
    )
    def test_3rd_party_auth_links_to_user_and_not_organization(self):
        # an organization and a person user share the same email address.
        # note that the Organization is created first.
        organization = Organization.objects.create(
            username="the_org",
            organization_owner=Person.objects.create(username="org_owner"),
            email="shared@qfield.cloud",
        )

        person = Person.objects.create(
            username="the_person",
            email="shared@qfield.cloud",
        )

        EmailAddress.objects.create(
            user=person,
            email="shared@qfield.cloud",
            verified=True,
            primary=True,
        )

        email_address = EmailAddress(email="shared@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNotNone(match_result)

        matched_user, matched_email = match_result

        # social account must be linked to the person user, not the organization.
        self.assertEqual(matched_user.type, User.Type.PERSON)
        self.assertEqual(matched_user.pk, person.pk)
        self.assertNotEqual(matched_user.pk, organization.pk)
        self.assertEqual(matched_email, "shared@qfield.cloud")
        self.assertEqual(matched_user.email, "shared@qfield.cloud")

    @override_settings(
        SOCIALACCOUNT_EMAIL_AUTHENTICATION=False,
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": False}},
    )
    def test_3rd_party_auth_does_not_link_when_not_allowed(self):
        person = Person.objects.create(
            username="the_person",
            email="the_email@qfield.cloud",
        )

        EmailAddress.objects.create(
            user=person,
            email="the_email@qfield.cloud",
            verified=True,
            primary=True,
        )

        email_address = EmailAddress(email="the_email@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNone(match_result)

    @override_settings(
        ACCOUNT_EMAIL_VERIFICATION=app_settings.EmailVerificationMethod.MANDATORY,
        SOCIALACCOUNT_PROVIDERS={"dummy": {"EMAIL_AUTHENTICATION": True}},
    )
    def test_3rd_party_auth_links_mail_case_insensitive(self):
        person = Person.objects.create(
            username="the_person",
            email="The_Email@qfield.cloud",
        )

        EmailAddress.objects.create(
            user=person,
            email="The_Email@qfield.cloud",
            verified=True,
            primary=True,
        )

        email_address = EmailAddress(email="the_email@qfield.cloud")
        sociallogin = SocialLogin(
            provider=self.dummy_provider, email_addresses=[email_address]
        )

        adapter = SocialAccountAdapter()
        match_result = adapter.authenticate_by_email(sociallogin)

        self.assertIsNotNone(match_result)

        matched_user, matched_email = match_result

        self.assertEqual(matched_user.pk, person.pk)
        self.assertEqual(matched_email, "The_Email@qfield.cloud")
        self.assertEqual(matched_user.email, "The_Email@qfield.cloud")
