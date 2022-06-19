import logging

from django.core.exceptions import ValidationError
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, OrganizationMember, User
from rest_framework.test import APITransactionTestCase

from ..models import AccountType

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_max_organization_members(self):
        """This tests quotas"""

        u1 = User.objects.create(username="u1")
        u2 = User.objects.create(username="u2")
        u3 = User.objects.create(username="u3")
        u4 = User.objects.create(username="u4")
        self._login(u1)

        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        unlimited_account_type = AccountType.objects.create(
            code="max_organization_members0",
            max_organization_members=0,
        )
        limited_account_type = AccountType.objects.create(
            code="max_organization_members1",
            max_organization_members=1,
        )

        o1.useraccount.account_type = unlimited_account_type
        o1.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o1)
        OrganizationMember.objects.create(member=u3, organization=o1)

        o1.useraccount.account_type = limited_account_type
        o1.useraccount.save()

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u4, organization=o1)

        o2 = Organization.objects.create(username="o2", organization_owner=u1)
        o2.useraccount.account_type = limited_account_type
        o2.useraccount.save()

        OrganizationMember.objects.create(member=u2, organization=o2)

        with self.assertRaises(ValidationError):
            OrganizationMember.objects.create(member=u3, organization=o2)
