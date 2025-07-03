from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project, ProjectCollaborator

from .utils import setup_subscription_plans


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
        self.assertEqual(project_collaborator.role, ProjectCollaborator.Roles.MANAGER)

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
