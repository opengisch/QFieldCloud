import logging

from django.core.exceptions import ValidationError
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, OrganizationMember, User
from qfieldcloud.core.tests.utils import setup_subscription_plans
from rest_framework.test import APITransactionTestCase

from ..models import Plan

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()

    def test_max_organization_members(self):
        """This tests quotas"""

        u1 = User.objects.create(username="u1")
        u2 = User.objects.create(username="u2")
        u3 = User.objects.create(username="u3")
        u4 = User.objects.create(username="u4")
        self._login(u1)

        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        unlimited_plan = Plan.objects.create(
            code="max_organization_members0",
            user_type=Plan.UserType.ORGANIZATION,
            max_organization_members=0,
        )
        limited_plan = Plan.objects.create(
            code="max_organization_members1",
            user_type=Plan.UserType.ORGANIZATION,
            max_organization_members=1,
        )

        o1.useraccount.plan = unlimited_plan
        o1.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o1)
        OrganizationMember.objects.create(member=u3, organization=o1)

        o1.useraccount.plan = limited_plan
        o1.useraccount.save()

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u4, organization=o1)

        o2 = Organization.objects.create(username="o2", organization_owner=u1)
        o2.useraccount.plan = limited_plan
        o2.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o2)

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u3, organization=o2)
