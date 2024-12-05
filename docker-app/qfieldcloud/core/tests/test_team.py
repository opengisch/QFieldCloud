import logging
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    TeamMember,
    Organization,
    OrganizationMember,
    Person,
    Team,
)
from rest_framework import status
from rest_framework.test import APITestCase

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class TeamsTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        self.u1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.u1)[0]

        self.u2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.u2)[0]

        self.u3 = Person.objects.create_user(
            username="user3", email="user3@email.com", password="abc123"
        )
        self.token3 = AuthToken.objects.get_or_create(user=self.u3)[0]

        self.o1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=Organization.Type.ORGANIZATION,
            organization_owner=self.u1,
        )

        OrganizationMember.objects.create(
            organization=self.o1,
            member=self.u2,
            role=OrganizationMember.Roles.ADMIN,
        )
        OrganizationMember.objects.create(
            organization=self.o1,
            member=self.u3,
            role=OrganizationMember.Roles.MEMBER,
        )

        team1_username = Team.format_team_name(self.o1.username, "team1")
        team2_username = Team.format_team_name(self.o1.username, "team2")

        self.t1 = Team.objects.create(
            username=team1_username,
            team_organization=self.o1,
        )
        self.t2 = Team.objects.create(
            username=team2_username,
            team_organization=self.o1,
        )

    def test_authorized_user_can_list_teams(self):
        """Test that an authorized user can list teams."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(f"/api/v1/organizations/{self.o1.username}/teams/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        teams = sorted(response.json(), key=lambda t: t["teamname"])

        self.assertListEqual(
            teams,
            [
                {
                    "teamname": self.t1.teamname,
                    "organization": self.o1.username,
                },
                {
                    "teamname": self.t2.teamname,
                    "organization": self.o1.username,
                },
            ],
        )

    def test_authorized_user_can_retrieve_team_detail(self):
        """Test that an authorized user can get team's details."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertJSONEqual(
            response.content.decode(),
            {
                "teamname": self.t1.teamname,
                "organization": self.o1.username,
            },
        )

    def test_unauthorized_user_cannot_create_team(self):
        """Ensure unauthorized users cannot create a team."""
        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/",
            {"username": "newteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username="newteam").count(), 0)

    def test_non_admin_user_cannot_create_team(self):
        """Ensure non-admin members cannot create a team."""
        self.assertEqual(Team.objects.filter(username="newteam").count(), 0)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/",
            {"username": "newteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username="newteam").count(), 0)

    def test_admin_user_can_create_team(self):
        """Test that an admin can create a team."""
        team_username = Team.format_team_name(self.o1.username, "newteam")

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/",
            {"teamname": "newteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_admin_user_cannot_create_team_with_empty_payload(self):
        """Test that an admin cannot add a team with empty payload."""
        current_number_of_teams = Team.objects.all().count()

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Team.objects.all().count(), current_number_of_teams)

    def test_unauthorized_user_cannot_update_team(self):
        """Ensure unauthorized users cannot update a team."""
        response = self.client.put(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/",
            {"username": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

    def test_non_admin_user_cannot_update_team(self):
        """Ensure non-admin members cannot update a team."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.put(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/",
            {"username": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

    def test_admin_user_can_update_team(self):
        """Test that an admin can update team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.put(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/",
            {"teamname": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        updated_team_username = Team.format_team_name(self.o1.username, "newteamname")

        self.t1.refresh_from_db()

        self.assertEqual(self.t1.username, updated_team_username)
        self.assertEqual(Team.objects.filter(username=updated_team_username).count(), 1)

    def test_admin_user_cannot_update_team_with_empty_payload(self):
        """Test that an admin can update team without a payload."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        old_team_name = self.t1.teamname

        response = self.client.put(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.t1.refresh_from_db()

        self.assertEqual(self.t1.teamname, old_team_name)

    def test_unauthorized_user_cannot_delete_team(self):
        """Ensure unauthorized users cannot delete a team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

    def test_non_admin_user_cannot_delete_team(self):
        """Ensure non-admin members cannot delete a team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username=self.t1).count(), 1)

    def test_admin_user_can_delete_team(self):
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 0)

    def test_unauthorized_user_cannot_list_teams(self):
        """Test that an unauthorized user cannot list teams."""
        response = self.client.get(f"/api/v1/organizations/{self.o1.username}/teams/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_user_can_list_team_members(self):
        """Test that team members can list other members of their team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        TeamMember.objects.create(team=self.t1, member=self.u2)
        TeamMember.objects.create(team=self.t1, member=self.u3)

        self.assertEqual(TeamMember.objects.filter(team=self.t1).count(), 2)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertJSONEqual(
            response.content.decode(),
            [
                {
                    "member": "user2",
                },
                {
                    "member": "user3",
                },
            ],
        )

    def test_non_admin_user_can_list_team_members(self):
        """Test that team members can list other members of their team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        TeamMember.objects.create(team=self.t1, member=self.u2)
        TeamMember.objects.create(team=self.t1, member=self.u3)

        self.assertEqual(TeamMember.objects.filter(team=self.t1).count(), 2)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertJSONEqual(
            response.content.decode(),
            [
                {
                    "member": "user2",
                },
                {
                    "member": "user3",
                },
            ],
        )

    def test_unauthorized_user_cannot_list_team_members(self):
        """Test that team members can list other members of their team."""
        response = self.client.get(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertJSONEqual(
            response.content.decode(),
            {"code": "not_authenticated", "message": "Not authenticated"},
        )

    def test_admin_user_can_add_member_to_team_by_username(self):
        """Test that an admin can add a member to a team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/",
            {
                "member": self.u3.username,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            TeamMember.objects.filter(team=self.t1, member=self.u3).count(), 1
        )

    def test_admin_user_can_add_member_to_team_by_email(self):
        """Test that an admin can add a member to a team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/",
            {
                "member": self.u3.email,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            TeamMember.objects.filter(team=self.t1, member=self.u3).count(), 1
        )

    def test_admin_user_can_delete_member_from_team(self):
        """Test that an admin can remove a member from a team."""
        TeamMember.objects.create(team=self.t1, member=self.u3)

        self.assertEqual(TeamMember.objects.filter(member=self.u3).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/{self.u3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(
            TeamMember.objects.filter(team=self.t1, member=self.u3).count(), 0
        )

    def test_non_admin_user_cannot_delete_member_from_team(self):
        """Test that an admin can remove a member from a team."""
        TeamMember.objects.create(team=self.t1, member=self.u3)

        self.assertEqual(TeamMember.objects.filter(member=self.u3).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/{self.u3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            TeamMember.objects.filter(team=self.t1, member=self.u3).count(), 1
        )

    def test_unauthorized_user_cannot_delete_member_from_team(self):
        """Test that an admin can remove a member from a team."""
        TeamMember.objects.create(team=self.t1, member=self.u3)

        self.assertEqual(TeamMember.objects.filter(member=self.u3).count(), 1)

        response = self.client.delete(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/{self.u3.username}/"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            TeamMember.objects.filter(team=self.t1, member=self.u3).count(), 1
        )

    def test_admin_user_cannot_create_team_member_with_empty_payload(self):
        """Test that an admin can add a member to a team."""
        self.assertEqual(Team.objects.filter(username=self.t1.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.o1.username}/teams/{self.t1.teamname}/members/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
