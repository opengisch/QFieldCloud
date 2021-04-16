from django.contrib.auth import get_user_model
from qfieldcloud.core import querysets_utils
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
)
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

User = get_user_model()


class QuerysetTestCase(APITestCase):
    def setUp(self):
        # user1 owns p1 and p2
        # user1 owns o1
        # user1 collaborates on p7
        self.user1 = User.objects.create_user(username="user1", password="abc123")
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # user2 owns p3 and p4
        # user2 admins o1
        self.user2 = User.objects.create_user(username="user2", password="abc123")
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # user2 owns p7 and p8
        # user2 is member of o1
        self.user3 = User.objects.create_user(username="user3", password="abc123")
        self.token3 = Token.objects.get_or_create(user=self.user3)[0]

        # organization1 owns p4 and p5
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            user_type=2,
            organization_owner=self.user1,
        )

        self.membership1 = OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.ADMIN,
        )

        self.membership2 = OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.Roles.MEMBER,
        )

        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        self.project2 = Project.objects.create(
            name="project2", is_public=True, owner=self.user1
        )

        self.project3 = Project.objects.create(
            name="project3", is_public=False, owner=self.user2
        )

        self.project4 = Project.objects.create(
            name="project4", is_public=True, owner=self.user2
        )

        self.project5 = Project.objects.create(
            name="project5", is_public=False, owner=self.organization1
        )

        self.project6 = Project.objects.create(
            name="project6", is_public=True, owner=self.organization1
        )

        self.project7 = Project.objects.create(
            name="project7", is_public=False, owner=self.user3
        )

        self.project8 = Project.objects.create(
            name="project8", is_public=True, owner=self.user3
        )

        self.collaborator1 = ProjectCollaborator.objects.create(
            project=self.project7,
            collaborator=self.user1,
            role=ProjectCollaborator.Roles.REPORTER,
        )

    def tearDown(self):
        # Remove all projects avoiding bulk delete in order to use
        # the overrided delete() function in the model
        for p in Project.objects.all():
            p.delete()

            User.objects.all().delete()
            # Remove credentials
            self.client.credentials()

    def test_get_users(self):
        # should get all the available users
        queryset = querysets_utils.get_users("")
        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.organization1.user_ptr in queryset)

        # should get all the available users
        queryset = querysets_utils.get_users("user3")
        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.user3 in queryset)

        # should get only the users that are not an organization
        queryset = querysets_utils.get_users("", exclude_organizations=True)
        self.assertEqual(len(queryset), 3)
        self.assertTrue(self.user1 in queryset)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)

        # should get all the users, that are not members or owners of an organization
        queryset = querysets_utils.get_users("", organization=self.organization1)
        self.assertEqual(len(queryset), 0)

        # should get all the users, that are not members or owner of a project
        queryset = querysets_utils.get_users("", project=self.project1)
        self.assertEqual(len(queryset), 3)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)
        self.assertTrue(self.organization1.user_ptr in queryset)

        # should get all the users, that are not members or owner of a project and are not an organization
        queryset = querysets_utils.get_users(
            "", project=self.project1, exclude_organizations=True
        )
        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.user2 in queryset)
        self.assertTrue(self.user3 in queryset)

    def test_projects_roles_and_role_origins(self):
        """
        Checks user_role and user_role_origin are correctly defined
        """

        def p(proj, user):
            return Project.objects.for_user(user).get(pk=proj.pk)

        # fmt: off
        self.assertEqual(p(self.project1, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project1, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project2, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project2, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project3, self.user1)
        self.assertEqual(p(self.project4, self.user1).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project4, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project5, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        self.assertEqual(p(self.project6, self.user1).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONOWNER.value)
        self.assertEqual(p(self.project7, self.user1).user_role, ProjectCollaborator.Roles.REPORTER)
        self.assertEqual(p(self.project7, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.COLLABORATOR.value)
        self.assertEqual(p(self.project8, self.user1).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project8, self.user1).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)

        with self.assertRaises(Project.DoesNotExist):
            p(self.project1, self.user2)
        self.assertEqual(p(self.project2, self.user2).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project2, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project3, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project3, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project4, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project4, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project5, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project5, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        self.assertEqual(p(self.project6, self.user2).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project6, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.ORGANIZATIONADMIN.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project7, self.user2)
        self.assertEqual(p(self.project8, self.user2).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project8, self.user2).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)

        with self.assertRaises(Project.DoesNotExist):
            p(self.project1, self.user3)
        self.assertEqual(p(self.project2, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project2, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project3, self.user3)
        self.assertEqual(p(self.project4, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project4, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        with self.assertRaises(Project.DoesNotExist):
            p(self.project5, self.user3)
        self.assertEqual(p(self.project6, self.user3).user_role, ProjectCollaborator.Roles.READER)
        self.assertEqual(p(self.project6, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PUBLIC.value)
        self.assertEqual(p(self.project7, self.user3).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project7, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        self.assertEqual(p(self.project8, self.user3).user_role, ProjectCollaborator.Roles.ADMIN)
        self.assertEqual(p(self.project8, self.user3).user_role_origin, ProjectQueryset.RoleOrigins.PROJECTOWNER.value)
        # fmt: on
