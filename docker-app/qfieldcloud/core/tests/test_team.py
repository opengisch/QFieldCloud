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

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.token3 = AuthToken.objects.get_or_create(user=self.user3)[0]

        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=Organization.Type.ORGANIZATION,
            organization_owner=self.user1,
        )

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

    def test_authorized_user_can_list_teams(self):
        """Test that an authorized user can list teams."""
        team1_username = Team.format_team_name(self.organization1.username, "team1")
        team2_username = Team.format_team_name(self.organization1.username, "team2")

        team1 = Team.objects.create(
            username=team1_username,
            team_organization=self.organization1,
        )
        team2 = Team.objects.create(
            username=team2_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team1.username).count(), 1)
        self.assertEqual(Team.objects.filter(username=team2.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization1.username}/teams/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_content = response.json()

        team_usernames = sorted([team["username"] for team in response_content])

        self.assertEqual(len(team_usernames), 2)
        self.assertEqual(team1.username, team_usernames[0])
        self.assertEqual(team2.username, team_usernames[1])

    def test_authorized_user_can_retrieve_team_detail(self):
        """Test that an authorized user can get team's details."""
        team_username = Team.format_team_name(self.organization1.username, "team1")

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_content = response.json()

        self.assertEqual(response_content["username"], team.username)
        self.assertEqual(response_content["organization"], self.organization1.username)

    def test_unauthorized_user_cannot_create_team(self):
        """Ensure unauthorized users cannot create a team."""

        self.assertEqual(Team.objects.filter(username="unauthorizedteam").count(), 0)

        response = self.client.post(
            f"/api/v1/organizations/{self.organization1.username}/teams/",
            {"username": "unauthorizedteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username="unauthorizedteam").count(), 0)

    def test_non_admin_user_cannot_create_team(self):
        """Ensure non-admin members cannot create a team."""

        self.assertEqual(Team.objects.filter(username="unauthorizedteam").count(), 0)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.organization1.username}/teams/",
            {"username": "unauthorizedteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username="unauthorizedteam").count(), 0)

    def test_unauthorized_user_cannot_update_team(self):
        """Ensure unauthorized users cannot update a team."""
        team_username = Team.format_team_name(
            self.organization1.username, "oldteamname"
        )

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/",
            {"username": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_non_admin_user_cannot_update_team(self):
        """Ensure non-admin members cannot update a team."""
        team_username = f"@{self.organization1.username}/oldteamname"

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/",
            {"username": "newteamname"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_unauthorized_user_cannot_delete_team(self):
        """Ensure unauthorized users cannot delete a team."""
        team_username = f"@{self.organization1.username}/teamtodelete"

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        response = self.client.delete(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_non_admin_user_cannot_delete_team(self):
        """Ensure non-admin members cannot delete a team."""
        team_username = Team.format_team_name(
            self.organization1.username, "teamtodelete"
        )

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token3.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_unauthorized_user_cannot_list_teams(self):
        """Test that an unauthorized user cannot list teams."""
        team1_username = Team.format_team_name(self.organization1.username, "team1")
        team2_username = Team.format_team_name(self.organization1.username, "team2")

        _team1 = Team.objects.create(
            username=team1_username,
            team_organization=self.organization1,
        )
        _team2 = Team.objects.create(
            username=team2_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team1_username).count(), 1)
        self.assertEqual(Team.objects.filter(username=team2_username).count(), 1)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization1.username}/teams/"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_user_can_create_team(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        team_username = Team.format_team_name(self.organization1.username, "newteam")

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.organization1.username}/teams/",
            {"username": "newteam"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

    def test_admin_user_can_update_team(self):
        team_username = f"@{self.organization1.username}/oldteamname"

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.put(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/",
            {"username": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        updated_team_username = f"@{self.organization1.username}/newteamname"
        team.refresh_from_db()
        self.assertEqual(team.username, updated_team_username)
        self.assertEqual(Team.objects.filter(username=updated_team_username).count(), 1)

    def test_admin_user_can_delete_team(self):
        team_username = f"@{self.organization1.username}/teamtodelete"

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team_username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.delete(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Team.objects.filter(username=team_username).count(), 0)

    def test_admin_user_can_list_team_members(self):
        """Test that team members can list other members of their team."""
        team_username = Team.format_team_name(self.organization1, "team_with_members")

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team.username).count(), 1)

        TeamMember.objects.create(team=team, member=self.user2)
        TeamMember.objects.create(team=team, member=self.user3)

        self.assertEqual(TeamMember.objects.filter(team=team).count(), 2)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/members/"
        )

        print("JSON response:", response.json())

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        member_usernames = sorted([member["member"] for member in response.json()])

        self.assertEqual(len(member_usernames), 2)
        self.assertEqual(
            TeamMember.objects.get(member=self.user2).member.id, member_usernames[0]
        )
        self.assertEqual(
            TeamMember.objects.get(member=self.user3).member.id, member_usernames[1]
        )

    def test_admin_user_add_member_to_team(self):
        """Test that an admin can add a member to a team."""

        team_username = Team.format_team_name(self.organization1, "team_with_members")

        team = Team.objects.create(
            username=team_username,
            team_organization=self.organization1,
        )

        self.assertEqual(Team.objects.filter(username=team.username).count(), 1)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        response = self.client.post(
            f"/api/v1/organizations/{self.organization1.username}/teams/{team.teamname}/members/",
            {"username": self.user3.username},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            TeamMember.objects.filter(team=team, member=self.user3).count(), 1
        )
