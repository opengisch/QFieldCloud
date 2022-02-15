import logging

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, OrganizationMember, User
from rest_framework import status
from rest_framework.test import APITestCase

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a user
        self.user2 = User.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        # Create a user
        self.user3 = User.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            user_type=2,
            organization_owner=self.user1,
        )

    def test_list_members(self):

        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )

        # Set user3 as admin of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.Roles.ADMIN,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/members/organization1/")

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["member"])

        self.assertEqual(len(json), 2)
        self.assertEqual(json[0]["member"], "user2")
        self.assertEqual(json[0]["role"], "member")
        self.assertEqual(json[1]["member"], "user3")
        self.assertEqual(json[1]["role"], "admin")

    def test_create_member(self):

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/members/organization1/",
            {
                "member": "user2",
                "role": "admin",
            },
        )

        self.assertTrue(status.is_success(response.status_code))

        members = OrganizationMember.objects.all()
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].organization, self.organization1)
        self.assertEqual(members[0].member, self.user2)
        self.assertEqual(members[0].role, OrganizationMember.Roles.ADMIN)

    def test_update_member(self):
        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.patch(
            "/api/v1/members/organization1/user2/",
            {
                "role": "member",
            },
        )

        self.assertTrue(status.is_success(response.status_code))

        members = OrganizationMember.objects.all()
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].organization, self.organization1)
        self.assertEqual(members[0].member, self.user2)
        self.assertEqual(members[0].role, OrganizationMember.Roles.MEMBER)

    def test_delete_member(self):

        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.delete("/api/v1/members/organization1/user2/")

        self.assertTrue(status.is_success(response.status_code))

        members = OrganizationMember.objects.all()
        self.assertEqual(len(members), 0)

    def test_admin_can_add_member(self):
        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        response = self.client.post(
            "/api/v1/members/organization1/",
            {
                "member": "user3",
                "role": "member",
            },
        )

        self.assertFalse(status.is_success(response.status_code))

        # Set user2 as admin of organization1
        obj = OrganizationMember.objects.all()[0]
        obj.role = OrganizationMember.Roles.ADMIN
        obj.save()

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        response = self.client.post(
            "/api/v1/members/organization1/",
            {
                "member": "user3",
                "role": "member",
            },
        )

        self.assertTrue(status.is_success(response.status_code))
