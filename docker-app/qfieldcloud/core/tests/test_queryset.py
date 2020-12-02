
from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from qfieldcloud.core.models import (
    Organization,
    Project,
    ProjectCollaborator
)
from qfieldcloud.core import querysets_utils

from .utils import testdata_path

User = get_user_model()


class QuerysetTestCase(APITestCase):
    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(
            username='user1',
            password='abc123')
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = User.objects.create_user(
            username='user2',
            password='abc123')
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username='organization1',
            password='abc123',
            user_type=2,
            organization_owner=self.user1,
        )

        # Create a private project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Create a public project
        self.project2 = Project.objects.create(
            name='project2',
            private=False,
            owner=self.user1)

        # Create a public project of user2
        self.project3 = Project.objects.create(
            name='project3',
            private=False,
            owner=self.user2)

        # Create a public project of organization1
        self.project4 = Project.objects.create(
            name='project4',
            private=False,
            owner=self.organization1)

        # Create a private project of organization1
        self.project5 = Project.objects.create(
            name='project5',
            private=True,
            owner=self.organization1)

    def tearDown(self):
        # Remove all projects avoiding bulk delete in order to use
        # the overrided delete() function in the model
        for p in Project.objects.all():
            p.delete()

            User.objects.all().delete()
            # Remove credentials
            self.client.credentials()

    def test_available_projects(self):

        queryset = querysets_utils.get_available_projects(
            self.user1, include_public=False)

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)

    def test_available_and_public_projects(self):

        queryset = querysets_utils.get_available_projects(
            self.user1, include_public=True)

        self.assertEqual(len(queryset), 4)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)
        self.assertTrue(self.project3 in queryset)
        self.assertTrue(self.project4 in queryset)

    def test_projects_of_owner_same_as_user(self):

        queryset = querysets_utils.get_projects_of_owner(
            self.user1, self.user1)

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project1 in queryset)
        self.assertTrue(self.project2 in queryset)

    def test_projects_of_owner_another_user(self):

        queryset = querysets_utils.get_projects_of_owner(
            self.user1, self.user2)

        # user1 is not a collaborator of any projects so only
        # public projects should be available
        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project3 in queryset)

    def test_projects_of_owner_organization(self):

        queryset = querysets_utils.get_projects_of_owner(
            self.user1, self.organization1)

        # user1 is not a collaborator of any projects so only
        # public projects should be available
        self.assertEqual(len(queryset), 1)
        self.assertTrue(self.project4 in queryset)

        # Add user1 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project5,
            collaborator=self.user1,
            role=ProjectCollaborator.ROLE_MANAGER)

        queryset = querysets_utils.get_projects_of_owner(
            self.user1, self.organization1)

        self.assertEqual(len(queryset), 2)
        self.assertTrue(self.project4 in queryset)
        self.assertTrue(self.project5 in queryset)
