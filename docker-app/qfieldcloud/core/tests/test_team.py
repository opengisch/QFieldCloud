import logging
from django.utils.timezone import now
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Team,
)
from rest_framework import status
from rest_framework.test import APITestCase

from .utils import set_subscription, setup_subscription_plans

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

        # Activate Subscriptions
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

    def test_list_teams(self):
        team1 = Team.objects.create(
            username=f"@{self.organization1.username}/team1",
            team_organization=self.organization1,
        )
        team2 = Team.objects.create(
            username=f"@{self.organization1.username}/team2",
            team_organization=self.organization1,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            f"/organizations/{self.organization1.username}/team/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        json_response = response.json()
        team_usernames = [team["username"] for team in json_response]

        self.assertIn(team1.username, team_usernames)
        self.assertIn(team2.username, team_usernames)

    def test_create_team(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            f"/organizations/{self.organization1.username}/team/",
            {"username": "newteam"},
        )

        self.assertTrue(status.is_success(response.status_code))

        team_username = f"@{self.organization1.username}/newteam"
        team_exists = Team.objects.filter(
            username=team_username, team_organization=self.organization1
        ).exists()
        self.assertTrue(team_exists)

    def test_retrieve_team_detail(self):
        """Test retrieving the details of a specific team."""
        team = Team.objects.create(
            username=f"@{self.organization1.username}/teamdetail",
            team_organization=self.organization1,
        )

        # Authenticate with the correct user token
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        # Make a GET request to retrieve the team details
        url = f"/organizations/{self.organization1.username}/team/teamdetail/"
        response = self.client.get(url)

        # Assert the response status is 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the response data
        json_response = response.json()
        self.assertEqual(json_response["username"], team.username)
        self.assertEqual(json_response["organization"], self.organization1.username)


    def test_update_team(self):
        team = Team.objects.create(
            username=f"@{self.organization1.username}/oldteamname",
            team_organization=self.organization1,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.put(
            f"/organizations/{self.organization1.username}/team/oldteamname/",
            {"username": "newteamname"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        updated_team_username = f"@{self.organization1.username}/newteamname"
        team.refresh_from_db()
        self.assertEqual(team.username, updated_team_username)

    
    def test_delete_team(self):
        team = Team.objects.create(
            username=f"@{self.organization1.username}/teamtodelete",
            team_organization=self.organization1,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.delete(
            f"/organizations/{self.organization1.username}/team/teamtodelete/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        team_exists = Team.objects.filter(
            username=team.username, team_organization=self.organization1
        ).exists()
        self.assertFalse(team_exists)

    # TODO 
    def test_non_member_cannot_access_team(self):
       pass

    # TODO 
    def test_member_can_access_team(self):
        pass