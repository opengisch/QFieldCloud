from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    ProjectCollaborator,
)
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.project.enums import ProjectCollaboratorRole
from qfieldcloud.project.models import Project


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.token2 = AuthToken.objects.get_or_create(user=self.user2)[0]

    def test_add_collaborator_via_api(self):
        project = Project.objects.create(
            name="api_collab_test",
            is_public=False,
            owner=self.user1,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.post(
            f"/api/v1/collaborators/{project.id}/",
            {
                "collaborator": "user2",
                "role": "manager",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()

        self.assertEqual(data["collaborator"], "user2")
        self.assertEqual(data["role"], "manager")
        self.assertEqual(data["project_id"], str(project.id))

        collaborators = ProjectCollaborator.objects.filter(project=project)

        self.assertEqual(collaborators.count(), 1)

        project_collaborator = collaborators.first()

        self.assertEqual(project_collaborator.collaborator, self.user2)
        self.assertEqual(project_collaborator.role, ProjectCollaboratorRole.MANAGER)

    def test_add_unknown_collaborator_bad_request(self):
        project = Project.objects.create(
            name="api_collab_bad",
            is_public=False,
            owner=self.user1,
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.post(
            f"/api/v1/collaborators/{project.id}/",
            {
                "collaborator": "no_such_user",
                "role": "reader",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _make_organization(self, collaborator_limit: int = -1) -> Organization:
        """Organization owned by `user1`, with `user2` as a member and a plan
        that allows `collaborator_limit` collaborators per private project."""
        organization = Organization.objects.create(
            username="org1",
            organization_owner=self.user1,
        )
        OrganizationMember.objects.create(organization=organization, member=self.user2)
        set_subscription(
            organization,
            "org_plan",
            max_premium_collaborators_per_private_project=collaborator_limit,
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        return organization

    def _add_collaborator(self, project, collaborator, role="reader"):
        """Adds `collaborator` to `project` through the collaborators API and asserts
        the request was accepted."""
        response = self.client.post(
            f"/api/v1/collaborators/{project.id}/",
            {"collaborator": collaborator.username, "role": role},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def test_add_non_member_to_org_project(self):
        """A non-member can be added to a public org project, but not a private one."""
        organization = self._make_organization()
        outsider = Person.objects.create_user(username="outsider", password="abc123")

        def add_non_org_member(project):
            return self.client.post(
                f"/api/v1/collaborators/{project.id}/",
                {"collaborator": "outsider", "role": "reader"},
            )

        with self.subTest("Test adding a non-organization member to a public project"):
            public_project = Project.objects.create(
                name="public_project", owner=organization, is_public=True
            )
            response = add_non_org_member(public_project)

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertTrue(
                ProjectCollaborator.objects.filter(
                    project=public_project, collaborator=outsider
                ).exists()
            )

        with self.subTest("Test adding a non-organization member to a private project"):
            private_project = Project.objects.create(
                name="private_project", owner=organization, is_public=False
            )
            response = add_non_org_member(private_project)

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(
                ProjectCollaborator.objects.filter(
                    project=private_project, collaborator=outsider
                ).exists()
            )

    def test_make_public_project_private_with_non_org_member_collaborator_is_forbidden(
        self,
    ):
        """Test that making a public project private is forbidden if it has a non-organization member collaborator."""
        organization = self._make_organization()
        outsider = Person.objects.create_user(username="outsider", password="abc123")
        project = Project.objects.create(
            name="public_project", owner=organization, is_public=True
        )
        self._add_collaborator(project, outsider)

        response = self.client.patch(
            f"/api/v1/projects/{project.id}/", {"is_public": False}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        project.refresh_from_db()
        self.assertTrue(project.is_public)

    def test_make_public_project_private_over_plan_limit_is_forbidden(self):
        """Test that making a public project private is forbidden if it exceeds the plan's collaborator limit."""
        organization = self._make_organization(collaborator_limit=1)
        member2 = Person.objects.create_user(username="member2", password="abc123")
        OrganizationMember.objects.create(organization=organization, member=member2)
        project = Project.objects.create(
            name="public_project", owner=organization, is_public=True
        )
        self._add_collaborator(project, self.user2)
        self._add_collaborator(project, member2)

        response = self.client.patch(
            f"/api/v1/projects/{project.id}/", {"is_public": False}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        project.refresh_from_db()
        self.assertTrue(project.is_public)
