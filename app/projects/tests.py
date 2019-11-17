import os
import shutil
import filecmp

from unittest import skip

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIRequestFactory
from .models import Repository


settings.MEDIA_ROOT += '_test'


def testdata_path(path):
    basepath = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basepath, 'testdata', path)


class RepositoryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()

        # Create a repository
        test_repo1 = Repository(
            name='test_repo1', is_public=True, owner=test_user1)
        test_repo1.save()

    def test_repository_content(self):
        repo = Repository.objects.get(id=1)
        self.assertEqual(repo.name, 'test_repo1')
        self.assertEqual(repo.is_public, True)
        self.assertEqual(str(repo.owner), 'test_user1')


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
        #shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

        # Remove credentials
        self.client.credentials()
        
    def tearDown(self):
        # Remove test's MEDIA_ROOT
        #shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

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
            self.client.get('/api/v1/').status_code))

    def test_unauthorized_without_token(self):
        # Project list should be denied for unauthorized users
        self.assertTrue(status.is_client_error(
            self.client.get('/api/v1/').status_code))

    @skip('Waiting refactoring')
    def test_file_upload(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

        file_path = testdata_path('file.txt')
        with open(file_path, "rb") as binaryfile :
            file_data = bytearray(binaryfile.read())
            #myArr = bytearray(binaryfile.read())
        print(file_data)

        with open(file_path) as fp:
            response = self.client.put('/api/v1/upload/file.txt', {'file': fp})
        #response = self.client.put('/api/v1/upload/file.txt',
        #                {
        #                    "file": file_data,
        #                }
        #)

        self.assertTrue(status.is_success(response.status_code))        

        # Check if the file is actually stored in the correct position
        stored_file = os.path.join(settings.MEDIA_ROOT, 'user_1', 'file.txt')
        self.assertTrue(os.path.isfile(stored_file))
        
        # Check if file content is still the same
        self.assertTrue(filecmp.cmp(file_path, stored_file))
