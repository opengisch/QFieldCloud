from django.contrib.auth import get_user_model
from qfieldcloud.core import querysets_utils
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
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
            role=OrganizationMember.ROLE_ADMIN,
        )

        self.membership2 = OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user3,
            role=OrganizationMember.ROLE_MEMBER,
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
            role=ProjectCollaborator.ROLE_REPORTER,
        )

    def tearDown(self):
        # Remove all projects avoiding bulk delete in order to use
        # the overrided delete() function in the model
        for p in Project.objects.all():
            p.delete()

            User.objects.all().delete()
            # Remove credentials
            self.client.credentials()

    def test_my_owned_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            ownerships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)

    def test_my_organization_owned_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            memberships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_my_organization_admin_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user2,
            self.user2,
            memberships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_my_collaboration_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            collaborations=True,
        )

        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project7 in queryset)

    def test_my_ownerships_and_memberships_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            ownerships=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_my_ownerships_and_collaborations_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            ownerships=True,
            collaborations=True,
        )

        self.assertEqual(len(queryset), 3)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project7 in queryset)

    def test_my_collaborations_and_memberships_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            collaborations=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 3)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)
        self.assertTrue(self.project7 in queryset)

    def test_my_ownerships_and_collaborations_and_memberships_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            ownerships=True,
            collaborations=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 5)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)
        self.assertTrue(self.project7 in queryset)

    def test_my_available_and_public_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            ownerships=True,
            collaborations=True,
            memberships=True,
            public=True,
        )

        self.assertEqual(len(queryset), 7)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project4 in queryset)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)
        self.assertTrue(self.project7 in queryset)
        self.assertTrue(self.project8 in queryset)

    def test_my_public_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user1,
            public=True,
        )

        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project4 in queryset)
        self.assertTrue(self.project6 in queryset)
        self.assertTrue(self.project8 in queryset)

    def test_another_user_projects(self):

        queryset = querysets_utils.get_available_projects(
            self.user2,
            self.user3,
            ownerships=True,
            collaborations=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project8 in queryset)

    def test_another_user_projects_where_collaborated(self):

        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.user3,
            ownerships=True,
            collaborations=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project8 in queryset)

    def test_another_user_projects_where_collaborated_reversed(self):
        queryset = querysets_utils.get_available_projects(
            self.user3,
            self.user1,
            ownerships=True,
            collaborations=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_own_organization_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user1,
            self.organization1,
            ownerships=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_administered_organization_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user2,
            self.organization1,
            ownerships=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project5 in queryset)
        self.assertTrue(self.project6 in queryset)

    def test_member_organization_projects(self):
        queryset = querysets_utils.get_available_projects(
            self.user3,
            self.organization1,
            ownerships=True,
            memberships=True,
        )

        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project6 in queryset)

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
