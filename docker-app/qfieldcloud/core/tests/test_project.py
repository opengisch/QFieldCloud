import logging

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    User,
)
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

    def test_create_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/projects/",
            {
                "name": "api_created_project",
                "owner": "user1",
                "description": "desc",
                "is_public": False,
            },
        )
        self.assertTrue(status.is_success(response.status_code))

        project = Project.objects.get(name="api_created_project")
        # Will raise exception if it doesn't exist

        self.assertEqual(str(project.owner), "user1")

    def test_create_project_invalid_name(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/projects/",
            {
                "name": "project$",
                "owner": "user1",
                "description": "desc",
                "is_public": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_public_projects(self):

        # Create a public project of user2
        self.project1 = Project.objects.create(
            name="project1", is_public=True, owner=self.user2
        )

        # Create a private project of user2
        self.project1 = Project.objects.create(
            name="project2", is_public=False, owner=self.user2
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/projects/?include-public=true")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "project1")
        self.assertEqual(response.data[0]["owner"], "user2")

    def test_list_collaborators_of_project(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.MANAGER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/collaborators/{}/".format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)

        json = response.json()
        json = sorted(json, key=lambda k: k["collaborator"])

        self.assertEqual(json[0]["collaborator"], "user2")
        self.assertEqual(json[0]["role"], "manager")

    def test_list_projects_of_authenticated_user(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Create another project of user1
        self.project2 = Project.objects.create(
            name="project2", is_public=False, owner=self.user1
        )

        # Create a project of user2 without access to user1
        self.project3 = Project.objects.create(
            name="project3", is_public=False, owner=self.user2
        )

        # Create a project of user2 with invalid access to user1
        # (invalid because project is not owned by an organization the user is part of)
        self.project4 = Project.objects.create(
            name="project4", is_public=False, owner=self.user2
        )

        ProjectCollaborator.objects.create(
            project=self.project4,
            collaborator=self.user1,
            role=ProjectCollaborator.Roles.MANAGER,
        )

        # Create a project of user2 with valid access to user1
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user2
        )
        self.project5 = Project.objects.create(
            name="project5", is_public=False, owner=org1
        )

        OrganizationMember.objects.create(
            organization=org1,
            member=self.user1,
        )
        ProjectCollaborator.objects.create(
            project=self.project5,
            collaborator=self.user1,
            role=ProjectCollaborator.Roles.MANAGER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/projects/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 3)

        json = response.json()
        json = sorted(json, key=lambda k: k["name"])

        self.assertEqual(json[0]["name"], "project1")
        self.assertEqual(json[0]["owner"], "user1")
        self.assertEqual(json[0]["user_role"], "admin")
        self.assertEqual(json[0]["user_role_origin"], "project_owner")
        self.assertEqual(json[1]["name"], "project2")
        self.assertEqual(json[1]["owner"], "user1")
        self.assertEqual(json[1]["user_role"], "admin")
        self.assertEqual(json[1]["user_role_origin"], "project_owner")
        self.assertEqual(json[2]["name"], "project5")
        self.assertEqual(json[2]["owner"], "org1")
        self.assertEqual(json[2]["user_role"], "manager")
        self.assertEqual(json[2]["user_role_origin"], "collaborator")

    def test_create_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/collaborators/{}/".format(self.project1.id),
            {
                "collaborator": "user2",
                "role": "editor",
            },
        )
        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 1)
        self.assertEqual(collaborators[0].project, self.project1)
        self.assertEqual(collaborators[0].collaborator, self.user2)
        self.assertEqual(collaborators[0].role, ProjectCollaborator.Roles.EDITOR)

    def test_get_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.REPORTER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get(
            "/api/v1/collaborators/{}/user2/".format(self.project1.id)
        )

        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        self.assertEqual(json["collaborator"], "user2")
        self.assertEqual(json["role"], "reporter")

    def test_update_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.REPORTER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.patch(
            "/api/v1/collaborators/{}/user2/".format(self.project1.id),
            {
                "role": "admin",
            },
        )

        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 1)
        self.assertEqual(collaborators[0].project, self.project1)
        self.assertEqual(collaborators[0].collaborator, self.user2)
        self.assertEqual(collaborators[0].role, ProjectCollaborator.Roles.ADMIN)

    def test_delete_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.REPORTER,
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.delete(
            "/api/v1/collaborators/{}/user2/".format(self.project1.id)
        )

        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 0)

    def test_delete_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        # Create a project of user1
        project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Delete the project
        response = self.client.delete("/api/v1/projects/{}/".format(project1.id))
        self.assertTrue(status.is_success(response.status_code))

        # The project should not exist anymore
        self.assertFalse(Project.objects.filter(id=project1.id).exists())

    def test_error_responses(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        # Create a project of user1
        project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user2
        )

        # Get the project without permissions
        response = self.client.get("/api/v1/projects/{}/".format(project1.id))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "api_error")

        # Get an unexisting project id
        response = self.client.get(
            "/api/v1/projects/{}/".format("a258db08-b1cb-4c34-a0cc-1e0e2a464f87")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "object_not_found")

        # Get a project without a valid project id
        response = self.client.get("/api/v1/projects/{}/".format("pizza"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_public_projecs(self):
        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=True, owner=self.user1
        )

        # Create another project of user2
        self.project2 = Project.objects.create(
            name="project2", is_public=True, owner=self.user2
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/projects/public", follow=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)

        json = response.json()
        json = sorted(json, key=lambda k: k["name"])

        self.assertEqual(json[0]["name"], "project1")
        self.assertEqual(json[0]["owner"], "user1")
        self.assertEqual(json[0]["user_role"], "admin")
        self.assertEqual(json[0]["user_role_origin"], "project_owner")
        self.assertEqual(json[1]["name"], "project2")
        self.assertEqual(json[1]["owner"], "user2")
        self.assertEqual(json[1]["user_role"], "reader")
        self.assertEqual(json[1]["user_role_origin"], "public")

    def test_private_project_memberships(self):
        """Tests for QF-1553 - limit collaboration on private projects"""

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        # Create a project with a collaborator
        u = User.objects.create(username="u")
        o = Organization.objects.create(username="o", organization_owner=u)
        p = Project.objects.create(name="p", owner=u, is_public=True)

        apiurl = f"/api/v1/projects/{p.pk}/"

        self.client.raise_request_exception = True

        def assert_no_role():
            response = self.client.get(apiurl, follow=True)
            self.assertEqual(response.status_code, 403)

        def assert_role(user_role, user_role_origin):
            response = self.client.get(apiurl, follow=True)
            self.assertEqual(response.status_code, 200)
            json = response.json()
            self.assertEqual(json["user_role"], user_role)
            self.assertEqual(json["user_role_origin"], user_role_origin)

        # Project is public, we have a public role
        assert_role(user_role="reader", user_role_origin="public")

        # Project is public, collaboration membership is valid
        ProjectCollaborator.objects.create(
            project=p, collaborator=self.user1, role=ProjectCollaborator.Roles.MANAGER
        )
        assert_role(user_role="manager", user_role_origin="collaborator")

        # If project is made private, the collaboration is invalid
        p.is_public = False
        p.save()
        assert_no_role()

        # Making the owner an organisation is not enough as user is not member of that org
        p.owner = o
        p.save()
        assert_no_role()

        # As the user must be member of the organisation
        OrganizationMember.objects.create(organization=o, member=self.user1)
        assert_role(user_role="manager", user_role_origin="collaborator")
