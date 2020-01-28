import os
import shutil
import filecmp
import tempfile

from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import Project, File
from .utils import testdata_path


# Use a different PRJECT_ROOT for the tests
settings.PROJECTS_ROOT += '_test'


class FileTestCase(APITransactionTestCase):

    def setUp(self):
        # Create a user
        self.user1 = get_user_model().objects.create_user(
            username='user1', password='abc123')
        self.user1.save()
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)
        self.project1.save()

        # TODO: use a custom test directory for the projects and
        # remove the directory after the test

    def tearDown(self):
        get_user_model().objects.all().delete()
        # Remove credentials
        self.client.credentials()
        Project.objects.all().delete()

        # Remove test's PROJECTS_ROOT
        shutil.rmtree(settings.PROJECTS_ROOT, ignore_errors=True)

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

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

        stored_file = os.path.join(str(self.project1.id), 'file.txt')
        self.assertTrue(File.objects.get(stored_file=stored_file))

        # Check if the file is actually stored in the correct position
        stored_file_path = os.path.join(
            settings.PROJECTS_ROOT,
            str(self.project1.id),
            'file.txt')
        self.assertTrue(os.path.isfile(stored_file_path))

        # Check if file content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file_path))

    # TODO: test overwrite of file
    # TODO: test push file in directory

    def test_pull_file(self):
        # TODO: insert the file directly instead of using API

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

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

        # Pull the file
        response = self.client.get(
            '/api/v1/projects/user1/project1/file.txt/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.filename, 'file.txt')

        temp_file = tempfile.NamedTemporaryFile()
        with open(temp_file.name, 'wb') as f:
            for _ in response.streaming_content:
                f.write(_)

        self.assertEqual(response.filename, 'file.txt')
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path('file.txt')))

    def test_list_files(self):
        # TODO: insert the file directly instead of using API

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

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

        response = self.client.get(
            '/api/v1/projects/user1/project1/files/')
        self.assertTrue(status.is_success(response.status_code))

        self.assertEqual(response.json()[0][0], 'file.txt')
        self.assertEqual(response.json()[0][1], 13)
