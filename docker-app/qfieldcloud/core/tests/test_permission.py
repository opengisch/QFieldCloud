import logging

from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import permissions_utils as perms
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Team,
    User,
)

from .utils import set_subscription, setup_subscription_plans, testdata_path

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

        # Activate subscriptions
        set_subscription((self.user1, self.user2), "default_user")
        set_subscription(self.organization1, "default_org")

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )
        self.project1.save()

    def test_collaborator_project_takeover(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/projects/", format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(1, len(response.data))
        self.assertEqual("project1", response.data[0].get("name"))

        project = Project.objects.get(pk=response.data[0].get("id"))

        response = self.client.patch(
            f"/api/v1/projects/{project.pk}/",
            {"name": "renamed-project", "owner": "organization1"},
        )
        self.assertTrue(status.is_success(response.status_code))

        # user2 doesn't get to see user1's organization's project
        self.client.logout()

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        response = self.client.get("/api/v1/projects/", format="json")
        self.assertEqual(0, len(response.data))

        # user2 is added to the project and the organization
        ProjectCollaborator.objects.create(
            project=project,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.READER,
        )
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
        )
        response = self.client.get("/api/v1/projects/", format="json")
        self.assertEqual(1, len(response.data))
        self.assertEqual("renamed-project", response.data[0].get("name"))

        # patch is denied
        response = self.client.patch(
            f"/api/v1/projects/{project.pk}/",
            {"name": "stolen-project", "owner": "user2"},
        )
        self.assertFalse(status.is_success(response.status_code))
        project.refresh_from_db()
        self.assertEqual("renamed-project", project.name)

    def test_reader_cannot_push(self):
        # Connect as user2
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        # Set user2 as a collaborator READER of project1
        self.collaborator1 = ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.READER,
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reporter_can_push(self):
        # Connect as user2
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        # Set user2 as a collaborator REPORTER of project1, and as part of the org owning the project
        self.project1.owner = self.organization1
        self.project1.save()
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
        )
        self.collaborator1 = ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.REPORTER,
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

    def test_cannot_list_files_of_private_project(self):
        # Connect as user2
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_team_as_collaborators(self):
        def assertBecomeCollaborator(u: User, p: Project, error: Exception = None):
            if error is None:
                self.assertTrue(perms.check_can_become_collaborator(u, p))
            else:
                with self.assertRaises(error):
                    perms.check_can_become_collaborator(u, p)

            self.assertEqual(perms.can_become_collaborator(u, p), error is None)

        # Create users
        u1 = Person.objects.create_user(username="u1")
        u2 = Person.objects.create_user(username="u2")
        u3 = Person.objects.create_user(username="u3")
        set_subscription((u1), "default_user")

        # Create organizations
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        o2 = Organization.objects.create(username="o2", organization_owner=u1)
        set_subscription((o1, o2), "default_org")

        # Create a team
        o1_t1 = Team.objects.create(username="@o1/o1_t1", team_organization=o1)

        p1 = Project.objects.create(name="p1", owner=u1)
        p2 = Project.objects.create(name="p2", owner=o1)
        p3 = Project.objects.create(name="p3", owner=o2)

        # user cannot collaborate on projects they own
        assertBecomeCollaborator(u1, p1, perms.AlreadyCollaboratorError)

        # user can be collaborators on their organization projects
        assertBecomeCollaborator(u1, p2, None)

        # user cannot collaborate on other's organization projects without being a member first
        assertBecomeCollaborator(u3, p2, perms.UserOrganizationRoleError)

        # user can collaborate on other's organization projects
        o1.members.create(member=u3)
        assertBecomeCollaborator(u3, p2, None)

        # user cannot collaborate twice on the same project
        p2.collaborators.create(collaborator=u3)
        assertBecomeCollaborator(u3, p2, perms.AlreadyCollaboratorError)

        # team cannot collaborate on project that is owned by a user
        assertBecomeCollaborator(o1_t1, p1, perms.TeamOrganizationRoleError)

        # team cannot collaborate on project that is not owned by the same organization
        assertBecomeCollaborator(o1_t1, p3, perms.TeamOrganizationRoleError)

        # team can collaborate on project that is owned by the same organization
        assertBecomeCollaborator(o1_t1, p2, None)

        # non-premium user cannot collaborate on private user project with max_premium_collaborators set to 0
        set_subscription(
            u1,
            is_premium=True,
            max_premium_collaborators_per_private_project=0,
        )
        assertBecomeCollaborator(u2, p1, perms.ReachedCollaboratorLimitError)

        # non-premium user cannot collaborate on private user project with max_premium_collaborators set to 1
        subscription = u1.useraccount.current_subscription
        subscription.plan.max_premium_collaborators_per_private_project = 1
        subscription.plan.save()
        assertBecomeCollaborator(u2, p1, perms.ExpectedPremiumUserError)

        # premium user can collaborate on private user project with max_premium_collaborators set to 1
        default_plan = u2.useraccount.current_subscription.plan
        set_subscription(
            u2,
            is_premium=True,
            max_premium_collaborators_per_private_project=0,
        )
        assertBecomeCollaborator(u2, p1, None)

        # non-premium user can collaborate on public user project with max_premium_collaborators set to 1
        subscription = u2.useraccount.current_subscription
        subscription.plan = default_plan
        subscription.plan.save()
        p1.is_public = True
        p1.save()
        assertBecomeCollaborator(u2, p1, None)

        # non-premium user can collaborate on public user project with max_premium_collaborators set to 0
        subscription.plan.max_premium_collaborators_per_private_project = 0
        subscription.plan.save()
        assertBecomeCollaborator(u2, p1, None)
