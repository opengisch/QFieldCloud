import os
import shutil
import filecmp

from unittest import skip

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from .models import Project, GenericFile


settings.MEDIA_ROOT += '_test'


def testdata_path(path):
    basepath = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basepath, 'testdata', path)


class ProjectTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()

        # Create a project
        test_project1 = Project(
            name='test_project1', is_public=True, owner=test_user1)
        test_project1.save()

    def test_project_content(self):
        project = Project.objects.get(id=1)
        self.assertEqual(project.name, 'test_project1')
        self.assertEqual(project.is_public, True)
        self.assertEqual(str(project.owner), 'test_user1')


class APITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()
        cls.token = Token.objects.get_or_create(user=test_user1)[0]

    def setUp(self):
        # Remove test's MEDIA_ROOT
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

        # Remove credentials
        self.client.credentials()

    def tearDown(self):
        # Remove test's MEDIA_ROOT
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

        # Remove credentials
        self.client.credentials()

    def test_register_user(self):
        response = self.client.post(
            '/api/v1/rest-auth/registration/',
            {
                "username": "pippo",
                "email": "pippo@topolinia.tp",
                "password1": "secure_pass123",
                "password2": "secure_pass123"
            }
        )
        self.assertTrue(status.is_success(response.status_code))

    def test_login_session_authentication(self):
        response = self.client.post(
            '/api/v1/rest-auth/login/',
            {
                "username": "test_user1",
                "password": "abc123"
            }
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['key'], self.token.key)

    def test_login_session_authentication_wrong_password(self):
        response = self.client.post(
            '/api/v1/rest-auth/login/',
            {
                "username": "test_user1",
                "password": "abc1234"
            }
        )
        self.assertTrue(status.is_client_error(response.status_code))
        self.assertFalse('key' in response.data)

    def test_token_authorization(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Project list should be visible now
        self.assertTrue(status.is_success(
            self.client.get('/api/v1/projects/').status_code))

    def test_unauthorized_without_token(self):
        # Project list should be denied for unauthorized users
        self.assertTrue(status.is_client_error(
            self.client.get('/api/v1/').status_code))

    def test_project_creation(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        response = self.client.post(
            '/api/v1/projects/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        project = Project.objects.get(id=1)
        self.assertEqual(project.name, 'test_project')
        self.assertEqual(project.is_public, True)
        self.assertEqual(str(project.owner), 'test_user1')

        self.assertEqual(len(Project.objects.all()), 1)

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create a project
        response = self.client.post(
            '/api/v1/projects/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('file.txt')
        # Push a file
        response = self.client.post(
            '/api/v1/projects/test_project/push/',
            {
                "datafile": open(file_path, 'rb')
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Check if the related entry is present in the db
        self.assertEqual(len(GenericFile.objects.all()), 1)
        stored_file_object = GenericFile.objects.get(id=1)
        self.assertEqual(stored_file_object.filename, 'file.txt')

        # Check if the file is actually stored in the correct position
        stored_file = os.path.join(settings.MEDIA_ROOT, 'user_1', 'file.txt')
        self.assertTrue(os.path.isfile(stored_file))

        # Check if file content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))

    def test_push_multiple_files(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create a project
        response = self.client.post(
            '/api/v1/projects/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        file_path = testdata_path('file.txt')
        file_path2 = testdata_path('file2.txt')

        # Push the files
        response = self.client.post(
            '/api/v1/projects/test_project/push/',
            {
                "datafile": [open(file_path, 'rb'), open(file_path2, 'rb')]
            },
            format='multipart'
        )
        self.assertTrue(status.is_success(response.status_code))

        # Check if the related entries are present in the db
        self.assertEqual(len(GenericFile.objects.all()), 2)
        stored_file_object = GenericFile.objects.get(id=1)
        self.assertEqual(stored_file_object.filename, 'file.txt')
        stored_file_object2 = GenericFile.objects.get(id=2)
        self.assertEqual(stored_file_object2.filename, 'file2.txt')
        
        # Check if the files are actually stored in the correct position
        stored_file = os.path.join(settings.MEDIA_ROOT, 'user_1', 'file.txt')
        self.assertTrue(os.path.isfile(stored_file))
        stored_file2 = os.path.join(settings.MEDIA_ROOT, 'user_1', 'file2.txt')
        self.assertTrue(os.path.isfile(stored_file2))

        # Check if files content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))
        self.assertTrue(filecmp.cmp(file_path2, stored_file2))


    @skip('not possible at the moment')
    def test_project_deletion(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create a project
        response = self.client.post(
            '/api/v1/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        # Delete it
        response = self.client.delete('/api/v1/1/')
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(Project.objects.all()), 0)

    @skip('not possible at the moment')
    def test_project_details(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create a project
        response = self.client.post(
            '/api/v1/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        # Retrieve details
        response = self.client.get('/api/v1/1/')
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(response.data['name'] == 'test_project')
        self.assertTrue(response.data['is_public'] is True)

    @skip('not possible at the moment')
    def test_project_update(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        # Create a project
        response = self.client.post(
            '/api/v1/',
            {
                "name": "test_project",
                "is_public": True
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        # Update values
        response = self.client.put(
            '/api/v1/1/',
            {
                "name": "new_name",
                "is_public": False
            }
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(response.data['name'] == 'new_name')
        self.assertTrue(response.data['is_public'] is False)

    @skip('Waiting refactoring')
    def test_file_upload(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        file_path = testdata_path('file.txt')
        with open(file_path, "rb") as binaryfile:
            file_data = bytearray(binaryfile.read())
            # myArr = bytearray(binaryfile.read())
        print(file_data)

        with open(file_path) as fp:
            response = self.client.put('/api/v1/upload/file.txt', {'file': fp})
        # response = self.client.put('/api/v1/upload/file.txt',
        #                {
        #                    "file": file_data,
        #                }
        # )

        self.assertTrue(status.is_success(response.status_code))

        # Check if the file is actually stored in the correct position
        stored_file = os.path.join(settings.MEDIA_ROOT, 'user_1', 'file.txt')
        self.assertTrue(os.path.isfile(stored_file))

        # Check if file content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))
