from django.test import TestCase
from django.urls import reverse
from qfieldcloud.core.models import Organization, Team, TeamMember, OrganizationMember, User, Person
from qfieldcloud.authentication.models import AuthToken

class TeamMemberViewTests(TestCase):
    
    def setUp(self):
       
        # Create a user
        self.user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1@example.com"
        )
        self.token1 = AuthToken.objects.get_or_create(
            user=self.user1,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Create a second user
        self.user2 = Person.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )
        self.token2 = AuthToken.objects.get_or_create(
            user=self.user2,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Create a second user
        self.user3 = Person.objects.create_user(
            username="user3", password="abc123", email="user3@example.com"
        )
        self.token3 = AuthToken.objects.get_or_create(
            user=self.user3,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

        owner = self.user1

        self.organization = Organization.objects.create(username="TestOrg",organization_owner=owner)
        self.team = Team.objects.get_or_create(username="thundercats", team_organization=self.organization)[0]
        t1 = TeamMember.objects.get_or_create(team=self.team, member=self.user1)

    #     # Assign the user to the organization
    #     OrganizationMember.objects.create(organization=self.organization, member=self.user)

    def test_add_team_member_success(self):
        """Test successfully adding a member to the team."""
        url = reverse('team_members', kwargs={'organization_name': self.organization.name, 'team_name': self.team.name})
        data = {'username': 'testuser'}

        # Make the POST request to add a user
        response = self.client.post(url, data)

        # Check that the user is added successfully
        self.assertEqual(response.status_code, 201)
        self.assertEqual(TeamMember.objects.filter(team=self.team, member=self.user).count(), 1)
        self.assertIn('testuser', response.json()['message'])

    def test_add_team_member_user_not_in_organization(self):
        """Test that adding a user who is not part of the organization fails."""
        url = reverse('team_members', kwargs={'organization_name': self.organization.name, 'team_name': self.team.name})
        data = {'username': 'otheruser'}

        # Make the POST request to add a user not in the organization
        response = self.client.post(url, data)

        # Check that the user is not added
        self.assertEqual(response.status_code, 403)
        self.assertIn('does not belong', response.json()['error'])

    def test_list_team_members(self):
        """Test listing team members."""

        url += reverse('team_members', kwargs={'organization_name': self.organization.username, 'team_name': self.team.username})

        # Make the GET request to list team members
        response = self.client.get(url)

        # Check the response
        self.assertEqual(response.status_code, 200)
        
        members = response.json()['members']
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]['username'], 'testuser')
