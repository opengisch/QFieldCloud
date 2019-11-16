from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIRequestFactory
from .models import Project


class ProjectTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()

        # Create a project
        test_project = Project(
            name='test_project', file_name='test_project.qgs', uploaded_by=test_user1)
        test_project.save()

    def test_project_content(self):
        project = Project.objects.get(id=1)
        self.assertEqual(project.name, 'test_project')
        self.assertEqual(project.file_name, 'test_project.qgs')
        self.assertEqual(str(project.uploaded_by), 'test_user1')


class APITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
       # Create a user
        test_user1 = User.objects.create_user(
            username='test_user1', password='abc123')
        test_user1.save()
        cls.token = Token.objects.get_or_create(user=test_user1)[0]


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

    # TODO: add token tests
