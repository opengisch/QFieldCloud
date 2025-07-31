import logging
from unittest.mock import patch

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    SHARED_DATASETS_PROJECT_NAME,
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Team,
    TeamMember,
)
from qfieldcloud.subscription.models import Subscription

from .utils import set_subscription, setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
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

        # 1) do not list the public projects by default
        response = self.client.get("/api/v1/projects/")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 0)

        # 1) list the public projects on request
        response = self.client.get("/api/v1/projects/?include-public=1")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "project1")
        self.assertEqual(response.data[0]["owner"], "user2")

        # 1) do not list the public projects for any other value than 1
        response = self.client.get("/api/v1/projects/?include-public=true")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 0)

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
        response = self.client.get(f"/api/v1/collaborators/{self.project1.id}/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)

        json = response.json()
        json = sorted(json, key=lambda k: k["collaborator"])

        self.assertEqual(json[0]["collaborator"], "user2")
        self.assertEqual(json[0]["role"], "manager")

    def test_list_filtered_projects(self):
        # Create a project of user1 with public access to user2
        Project.objects.create(name="project1", is_public=True, owner=self.user1)

        # Create a project of user1 without access to user2
        Project.objects.create(name="project2", is_public=False, owner=self.user1)

        # Create a private project of user2
        Project.objects.create(name="project1", is_public=False, owner=self.user2)

        # Create a public project of user2
        Project.objects.create(name="project2", is_public=True, owner=self.user2)

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)

        # 1) list non-public projects for specific user name other than the logged in user
        response = self.client.get("/api/v1/projects/?owner=user1")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 0)

        # 1) list all projects (including public ones) for specific user name other than the logged in user
        response = self.client.get("/api/v1/projects/?owner=user1&include-public=1")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "project1")
        self.assertEqual(response.data[0]["owner"], "user1")

        # 2) list projects for specific user name matching logged in user
        response = self.client.get("/api/v1/projects/?owner=user2")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)

        json = response.json()
        json = sorted(json, key=lambda k: k["name"])
        self.assertEqual(json[0]["name"], "project1")
        self.assertEqual(json[0]["owner"], "user2")
        self.assertEqual(json[1]["name"], "project2")
        self.assertEqual(json[1]["owner"], "user2")

        # 3) list project for specific user name (matching logged in user) and project name
        response = self.client.get("/api/v1/projects/?owner=user2&name=project2")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "project2")
        self.assertEqual(response.data[0]["owner"], "user2")

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

        self.project4 = Project.objects.create(
            name="project4", is_public=False, owner=self.user2
        )

        ProjectCollaborator.objects.create(
            project=self.project4,
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
        self.assertEqual(json[2]["user_role"], "manager")
        self.assertEqual(json[2]["user_role_origin"], "collaborator")

    def test_create_collaborator(self):
        # Create a project of user1
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            f"/api/v1/collaborators/{self.project1.id}/",
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
        response = self.client.get(f"/api/v1/collaborators/{self.project1.id}/user2/")

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
            f"/api/v1/collaborators/{self.project1.id}/user2/",
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
            f"/api/v1/collaborators/{self.project1.id}/user2/"
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
        response = self.client.delete(f"/api/v1/projects/{project1.id}/")
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
        response = self.client.get(f"/api/v1/projects/{project1.id}/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "permission_denied")

        # Get an unexisting project id
        response = self.client.get(
            "/api/v1/projects/{}/".format("a258db08-b1cb-4c34-a0cc-1e0e2a464f87")
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
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
        u = Person.objects.create(username="u")
        o = Organization.objects.create(username="o", organization_owner=u)
        p = Project.objects.create(name="p", owner=u, is_public=True)

        set_subscription(u, max_premium_collaborators_per_private_project=0)

        apiurl = f"/api/v1/projects/{p.pk}/"

        self.client.raise_request_exception = True

        def assert_no_role():
            response = self.client.get(apiurl, follow=True)
            self.assertEqual(response.status_code, 403)

        def assert_role(role, origin):
            response = self.client.get(apiurl, follow=True)
            self.assertEqual(response.status_code, 200)
            json = response.json()
            self.assertEqual(json["user_role"], role)
            self.assertEqual(json["user_role_origin"], origin)

        # Project is public, we have a public role
        assert_role("reader", "public")

        # Project is public, collaboration membership is valid
        ProjectCollaborator.objects.create(
            project=p, collaborator=self.user1, role=ProjectCollaborator.Roles.MANAGER
        )
        assert_role("manager", "collaborator")

        # If project is made private, the collaboration is invalid
        p.is_public = False
        p.save()
        assert_no_role()

        # Making the owner an organization is not enough as user is not member of that org
        p.owner = o
        p.save()
        assert_no_role()

        # As the user must be member of the organization
        OrganizationMember.objects.create(organization=o, member=self.user1)
        assert_role("manager", "collaborator")

    def test_add_project_collaborator_without_being_org_member(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        p1 = Project.objects.create(name="p1", owner=o1, is_public=False)

        # cannot add project collaborator if not already an org member
        with self.assertRaises(ValidationError):
            ProjectCollaborator.objects.create(
                project=p1, collaborator=u2, role=ProjectCollaborator.Roles.MANAGER
            )

    def test_direct_collaborators(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        p1 = Project.objects.create(name="p1", owner=o1, is_public=False)

        OrganizationMember.objects.create(organization=o1, member=u2)
        c1 = ProjectCollaborator.objects.create(
            project=p1,
            collaborator=u2,
            role=ProjectCollaborator.Roles.MANAGER,
            is_incognito=False,
        )

        self.assertEqual(len(p1.direct_collaborators), 1)

        c1.is_incognito = True
        c1.save()

        self.assertEqual(len(p1.direct_collaborators), 0)

    def test_add_project_collaborator_and_being_org_member(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        p1 = Project.objects.create(name="p1", owner=o1, is_public=False)

        # add project collaborator if the user is already an organization member
        OrganizationMember.objects.create(organization=o1, member=u2)
        ProjectCollaborator.objects.create(
            project=p1, collaborator=u2, role=ProjectCollaborator.Roles.MANAGER
        )

    def test_add_team_member_without_being_org_member(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        t1 = Team.objects.create(username="t1", team_organization=o1)

        # cannot add team member if not already an org members
        with self.assertRaises(ValidationError):
            TeamMember.objects.create(team=t1, member=u2)

    def test_add_team_member_and_being_org_member(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        t1 = Team.objects.create(username="t1", team_organization=o1)

        # add team member if not already an org members
        OrganizationMember.objects.create(organization=o1, member=u2)
        TeamMember.objects.create(team=t1, member=u2)

    def test_delete_org_member_should_delete_team_membership(self):
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        t1 = Team.objects.create(username="t1", team_organization=o1)

        # deleting an organization member via queryset should also delete team membership
        OrganizationMember.objects.create(organization=o1, member=u2)
        TeamMember.objects.create(team=t1, member=u2)

        self.assertEqual(TeamMember.objects.filter(team=t1, member=u2).count(), 1)

        OrganizationMember.objects.filter(organization=o1, member=u2).delete()

        self.assertEqual(TeamMember.objects.filter(team=t1, member=u2).count(), 0)

        # deleting an organization member via model should also delete team membership
        om1 = OrganizationMember.objects.create(organization=o1, member=u2)
        TeamMember.objects.create(team=t1, member=u2)

        self.assertEqual(TeamMember.objects.filter(team=t1, member=u2).count(), 1)

        om1.delete()

        self.assertEqual(TeamMember.objects.filter(team=t1, member=u2).count(), 0)

    def test_create_project_by_inactive_user(self):
        p1 = Project.objects.create(
            name="p1",
            owner=self.user1,
        )

        subscription = self.user1.useraccount.current_subscription
        subscription.status = Subscription.Status.INACTIVE_DRAFT
        subscription.save()

        # Make sure the user is inactive
        self.assertFalse(self.user1.useraccount.current_subscription.is_active)

        # Can create project if user's subscription is inactive
        Project.objects.create(
            name="p2",
            owner=self.user1,
        )

        # Can still modify existing project
        p1.name = "p1-modified"
        p1.save()

    def test_create_project_if_user_is_over_quota(self):
        plan = self.user1.useraccount.current_subscription.plan

        # Create a project that uses all the storage
        more_bytes_than_plan = (plan.storage_mb * 1000 * 1000) + 1
        p1 = Project.objects.create(
            name="p1",
            owner=self.user1,
            file_storage_bytes=more_bytes_than_plan,
        )

        # Can create another project if the user's plan is over quota
        Project.objects.create(
            name="p2",
            owner=self.user1,
        )

        # Can still modify existing project
        p1.name = "p1-modified"
        p1.save()

    def test_localized_layers_property(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(name="project_with_layers", owner=self.user1)

        # Fake the property manually for testing purpose
        project._localized_layers = [{"filename": "localized:layer1.tif"}]

        with patch(
            "qfieldcloud.core.models.Project.localized_layers",
            new_callable=lambda: property(lambda self: self._localized_layers),
        ):
            layers = project.localized_layers
            self.assertEqual(len(layers), 1)
            self.assertEqual(layers[0]["filename"], "localized:layer1.tif")

    def test_project_serializer_shared_datasets_project_id(self):
        """Test that ProjectSerializer returns the correct shared_datasets_project_id."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(name="project", owner=self.user1)
        localized_project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
        )

        response = self.client.get(f"/api/v1/projects/{project.id}/")

        self.assertEqual(response.status_code, 200)

        json = response.json()

        self.assertEqual(json["shared_datasets_project_id"], str(localized_project.id))

    def test_project_serializer_is_shared_datasets_project(self):
        """Test that ProjectSerializer returns is_shared_datasets_project correctly."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(name="project", owner=self.user1)
        localized_project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
        )

        response = self.client.get(f"/api/v1/projects/{project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_shared_datasets_project"])

        response = self.client.get(f"/api/v1/projects/{localized_project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_shared_datasets_project"])

    def test_get_shared_datasets_project_exists(self):
        """Test Project.shared_datasets_project returns the project if found."""
        project = Project.objects.create(name="project", owner=self.user1)
        localized_project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
        )

        self.assertIsNotNone(project.shared_datasets_project)
        self.assertEqual(project.shared_datasets_project.id, localized_project.id)

    def test_get_shared_datasets_project_missing(self):
        """Test Project.shared_datasets_project returns None if not found."""
        project = Project.objects.create(name="project", owner=self.user1)

        self.assertIsNone(project.shared_datasets_project)

    def test_get_missing_localized_layers_when_no_localized_project(self):
        """Test get_missing_localized_layers returns all localized layers if no shared datasets project exists."""
        project = Project.objects.create(name="project", owner=self.user1)

        project.project_details = {
            "layers_by_id": {
                "layer1": {"is_localized": True, "filename": "localized:layer1.gpkg"},
                "layer2": {"is_localized": False, "filename": "normal_layer.gpkg"},
                "layer3": {"is_localized": True, "filename": "localized:layer3.gpkg"},
            }
        }

        project.save()

        missing_layers = project.get_missing_localized_layers()
        missing_filenames = [layer["filename"] for layer in missing_layers]

        self.assertEqual(len(missing_filenames), 2)
        self.assertIn("localized:layer1.gpkg", missing_filenames)
        self.assertIn("localized:layer3.gpkg", missing_filenames)

    def test_get_some_missing_localized_layers(self):
        """Test that get_missing_localized_layers returns multiple missing layers."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(
            name="project_get_some_missing", owner=self.user1
        )

        missing_layers_mock = [
            {"filename": "localized:missing_layer1.tif"},
            {"filename": "localized:missing_layer2.tif"},
        ]

        with patch.object(
            Project,
            "get_missing_localized_layers",
            return_value=missing_layers_mock,
        ):
            missing_layers = project.get_missing_localized_layers()

            self.assertEqual(len(missing_layers), 2)
            self.assertEqual(
                missing_layers[0]["filename"], "localized:missing_layer1.tif"
            )
            self.assertEqual(
                missing_layers[1]["filename"], "localized:missing_layer2.tif"
            )

    def test_get_no_missing_localized_layers(self):
        """Test that get_missing_localized_layers returns an empty list when no missing layers."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(
            name="project_get_no_missing", owner=self.user1
        )

        with patch.object(
            Project,
            "get_missing_localized_layers",
            return_value=[],
        ):
            missing_layers = project.get_missing_localized_layers()

            self.assertEqual(missing_layers, [])
            self.assertEqual(len(missing_layers), 0)

    def test_get_missing_localized_layers_method(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.create(name="project_get_missing", owner=self.user1)

        with patch.object(
            Project,
            "get_missing_localized_layers",
            return_value=[{"filename": "localized:missing_layer.tif"}],
        ):
            missing_layers = project.get_missing_localized_layers()

            self.assertEqual(len(missing_layers), 1)
            self.assertEqual(
                missing_layers[0]["filename"], "localized:missing_layer.tif"
            )

    def test_get_project_details_for_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        _project = Project.objects.create(name="project_to_repackage", owner=self.user1)

        response = self.client.get("/api/v1/projects/")

        self.assertEquals(response.status_code, status.HTTP_200_OK)

        payload = response.json()

        self.assertEquals(len(payload), 1)

        project_json = payload[0]

        self.assertIn("name", project_json)
        self.assertIsInstance(project_json["name"], str)
        self.assertIn("owner", project_json)
        self.assertIsInstance(project_json["owner"], str)
        self.assertIn("description", project_json)
        self.assertIsInstance(project_json["description"], str)
        self.assertIn("user_role", project_json)
        self.assertIsInstance(project_json["user_role"], str)
        self.assertIn("is_public", project_json)
        self.assertIsInstance(project_json["is_public"], bool)
        self.assertIn("can_repackage", project_json)
        self.assertIsInstance(project_json["can_repackage"], bool)
        self.assertIn("needs_repackaging", project_json)
        self.assertIsInstance(project_json["needs_repackaging"], bool)

    def test_seamless_projects_fetching_with_public_ones(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        # user1's projects
        Project.objects.create(name="private_project_of_user1", owner=self.user1)
        Project.objects.create(
            name="public_project_of_user1", owner=self.user1, is_public=True
        )

        # user2's projects
        Project.objects.create(name="private_project_of_user2", owner=self.user2)
        Project.objects.create(
            name="public_project_of_user2", owner=self.user2, is_public=True
        )

        # organization1's project
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        Project.objects.create(name="private_project_of_org1", owner=org1)
        Project.objects.create(
            name="public_project_of_org1", owner=org1, is_public=True
        )

        # organization2's project
        org2 = Organization.objects.create(
            username="org2", organization_owner=self.user2
        )
        Project.objects.create(name="private_project_of_org2", owner=org2)
        Project.objects.create(
            name="public_project_of_org2", owner=org2, is_public=True
        )

        data = self.client.get(
            "/api/v1/projects/",
        ).json()

        self.assertEqual(len(data), 4)

        self.assertEqual(data[0]["owner"], "org1")
        self.assertEqual(data[0]["name"], "private_project_of_org1")
        self.assertFalse(data[0]["is_public"])

        self.assertEqual(data[1]["owner"], "org1")
        self.assertEqual(data[1]["name"], "public_project_of_org1")
        self.assertTrue(data[1]["is_public"])

        self.assertEqual(data[2]["owner"], "user1")
        self.assertEqual(data[2]["name"], "private_project_of_user1")
        self.assertFalse(data[2]["is_public"])

        self.assertEqual(data[3]["owner"], "user1")
        self.assertEqual(data[3]["name"], "public_project_of_user1")
        self.assertTrue(data[3]["is_public"])
