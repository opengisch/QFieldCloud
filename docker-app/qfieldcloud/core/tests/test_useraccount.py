import logging

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import Organization, OrganizationMember, Person
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.subscription.models import PackageType, get_subscription_model

logging.disable(logging.CRITICAL)

Subscription = get_subscription_model()


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()
        PackageType.get_storage_package_type.cache_clear()

    def test_has_premium_support_with_nonpremium_plan(self):
        u1 = Person.objects.create(username="u1")

        # a user with non-premium subscription plan has no premium support
        set_subscription(u1, is_premium=False)
        self.assertFalse(u1.useraccount.has_premium_support)

    def test_has_premium_support_with_premium_plan(self):
        # a user with non-premium subscription plan has no premium support
        u1 = Person.objects.create(username="u1")

        self.assertFalse(u1.useraccount.has_premium_support)

        set_subscription(u1, is_premium=True)

        self.assertTrue(u1.useraccount.has_premium_support)

    def test_has_premium_support_with_premium_organization_ownership(self):
        # a user with a premium organization has premium support
        u1 = Person.objects.create(username="u1")

        set_subscription(u1, is_premium=False)

        self.assertFalse(u1.useraccount.has_premium_support)

        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        set_subscription(o1, is_premium=True)

        self.assertTrue(u1.useraccount.has_premium_support)

    def test_has_premium_support_with_premium_organization_membership(self):
        # a user who is a member of a premium organization has premium support
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u2)

        set_subscription(u1, is_premium=False)

        self.assertFalse(u1.useraccount.has_premium_support)

        set_subscription(o1, is_premium=True)

        self.assertFalse(u1.useraccount.has_premium_support)

        membership = o1.members.create(member=u1, role=OrganizationMember.Roles.MEMBER)

        self.assertFalse(u1.useraccount.has_premium_support)

        membership.role = OrganizationMember.Roles.ADMIN
        membership.save()

        self.assertTrue(u1.useraccount.has_premium_support)

    def test_deleting_the_user_deletes_the_avatar(self):
        u1 = Person.objects.create_user(
            username="u1", password="u1", email="same@example.com"
        )

        u1.useraccount.avatar = ContentFile("<svg />", "avatar.svg")
        u1.useraccount.save()

        storage_filename = "account/u1/avatars/avatar.svg"

        self.assertTrue(storages["default"].exists(storage_filename))

        u1.delete()

        self.assertFalse(storages["default"].exists(storage_filename))
