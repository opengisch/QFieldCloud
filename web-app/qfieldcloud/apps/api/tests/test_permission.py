import shutil
from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import Project, ProjectCollaborator
from .utils import testdata_path

User = get_user_model()

# Use a different PRJECT_ROOT for the tests
settings.PROJECTS_ROOT += '_test'


class PermissionTestCase(APITransactionTestCase):

    def setUp(self):
        # Create a user (owner)
        self.user1 = User.objects.create_user(
            username='user1', password='abc123')
        self.user1.save()
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = User.objects.create_user(
            username='user2', password='abc123')
        self.user2.save()
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)
        self.project1.save()

        # Create a collaborator
        self.collaborator1 = ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.ROLE_READER)

    def tearDown(self):
        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()
        Project.objects.all().delete()

        # Remove test's PROJECTS_ROOT
        shutil.rmtree(settings.PROJECTS_ROOT, ignore_errors=True)

    def test_reader_cannot_push(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2.key)

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reporter_can_push(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2.key)

        self.collaborator1.role = ProjectCollaborator.ROLE_REPORTER
        self.collaborator1.save()

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/user1/project1/push/',
            {
                "file": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))
