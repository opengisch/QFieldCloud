import logging
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Team,
    TeamMember,
)
from rest_framework import status
from rest_framework.test import APITestCase

from .utils import set_subscription, setup_subscription_plans

logging.disable(logging.CRITICAL)

class TeamMembersTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Creating users
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        self.user4 = Person.objects.create_user(username="user4", password="abc123")
        self.token4 = AuthToken.objects.get_or_create(user=self.user4)[0]

        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=Organization.Type.ORGANIZATION,
            organization_owner=self.user1,
        )

        # Activate subscription
        set_subscription(self.organization1, "default_org")


        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.ADMIN,
        )
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.team = Team.objects.create(
            username=f"@{self.organization1.username}/teamwithmembers",
            team_organization=self.organization1,
        )

    def test_add_member_to_team(self):
        """Test that an admin can add a member to a team."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        
         # Construct the URL using organization_name and team_name
        url = f"/organizations/{self.organization1.username}/team/{self.team.teamname}/members/"
        
        response = self.client.post(
            url,
            {"username": self.user3.username}, 
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(TeamMember.objects.filter(team=self.team, member=self.user3).exists())

    def test_list_team_members(self):
        """Test that team members can list other members of their team."""
        TeamMember.objects.create(team=self.team, member=self.user2)
        TeamMember.objects.create(team=self.team, member=self.user3)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        member_usernames = [member["member"] for member in response.json()]
        self.assertIn(self.user2.username, member_usernames)
        self.assertIn(self.user3.username, member_usernames)
 
    def test_remove_member_from_team(self):
        """Test that an admin can remove a member from a team."""
        TeamMember.objects.create(team=self.team, member=self.user3)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        
        response = self.client.delete(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/{self.user3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TeamMember.objects.filter(team=self.team, member=self.user3).exists())

    def test_non_member_cannot_access_team_members(self):
        """Test that non-members cannot access the team members list."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token4.key)
        response = self.client.get(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_access_team_members(self):
        """Test that a team member can access the team members list."""
        TeamMember.objects.create(team=self.team, member=self.user3)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)
        response = self.client.get(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_team_member_by_non_admin(self):
        """Test that only admins can remove a member from the team."""
        TeamMember.objects.create(team=self.team, member=self.user3)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)
        response = self.client.delete(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/{self.user3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_delete_team_member(self):
        """Test that an admin can delete a team member."""
        TeamMember.objects.create(team=self.team, member=self.user3)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        response = self.client.delete(
            f"/organizations/{self.organization1.username}/team/teamwithmembers/members/{self.user3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TeamMember.objects.filter(team=self.team, member=self.user3).exists())
