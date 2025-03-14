import calendar
import logging
import uuid
from datetime import timedelta

from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Delta,
    Job,
    Organization,
    OrganizationMember,
    Person,
    Project,
)

from .utils import set_subscription, setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a user
        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        # Create a user
        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        # Create a staff user
        self.user4 = Person.objects.create_user(
            username="user4", password="abc123", is_staff=True
        )
        self.token4 = AuthToken.objects.get_or_create(user=self.user4)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

        # Activate Subscriptions
        set_subscription(self.organization1, "default_org")

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
        self.assertEqual(members[0].created_by, self.user1)
        self.assertEqual(members[0].updated_by, self.user1)

    def test_update_member(self):
        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
            created_by=self.user1,
            updated_by=self.user1,
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
        self.assertEqual(members[0].created_by, self.user1)
        self.assertEqual(members[0].updated_by, self.user1)

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

    def test_created_by_set_to_none_on_user_deletion(self):
        creator = Person.objects.create(username="creator")
        member = Person.objects.create(username="member")

        org_member = OrganizationMember.objects.create(
            organization=self.organization1,
            member=member,
            role="admin",
            created_by=creator,
        )

        creator.delete()

        org_member.refresh_from_db()

        self.assertIsNone(org_member.created_by)

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

    def test_active_users_count(self):
        """Tests billable users calculations"""

        # Set user1 and user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.Roles.MEMBER,
        )
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user4,
            role=OrganizationMember.Roles.MEMBER,
        )

        # Create a project owned by the organization
        project1 = Project.objects.create(name="p1", owner=self.organization1)

        def _active_users_count(base_date=None):
            """Helper to get count of billable users"""
            if base_date is None:
                base_date = now()

            # Note: we can't easily mock dates as the worker can update jobs in the background
            # with the current date
            start_date = base_date.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end_date = base_date.replace(
                day=calendar.monthrange(base_date.year, base_date.month)[1]
            )
            return self.organization1.active_users(start_date, end_date).count()

        # Initially, there is no billable user
        self.assertEqual(_active_users_count(), 0)

        # user2 creates a job
        Job.objects.create(
            project=project1,
            created_by=self.user2,
        )
        # There is now 1 billable user
        self.assertEqual(_active_users_count(), 1)

        # user2 creates a delta
        Delta.objects.create(
            deltafile_id=uuid.uuid4(),
            project=project1,
            content="delta",
            client_id=uuid.uuid4(),
            created_by=self.user2,
        )
        # There is still 1 billable user
        self.assertEqual(_active_users_count(), 1)

        # user3 creates a job
        Job.objects.create(
            project=project1,
            created_by=self.user3,
        )
        # There are 2 billable users
        self.assertEqual(_active_users_count(), 2)

        # user3 leaves the organization
        OrganizationMember.objects.filter(member=self.user3).delete()

        # There are still 2 billable users
        self.assertEqual(_active_users_count(), 2)

        # Report at a different time is empty
        self.assertEqual(_active_users_count(now() + timedelta(days=365)), 0)

        # user4 creates a job
        Job.objects.create(
            project=project1,
            created_by=self.user4,
        )
        # There are still 2 billable users, because user4 is staff
        self.assertEqual(_active_users_count(), 2)
