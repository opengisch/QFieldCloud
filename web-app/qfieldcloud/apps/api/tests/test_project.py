from unittest import skip

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import Project


class ProjectTestCase(APITestCase):

    def setUp(self):
        # Create a user
        self.user1 = get_user_model().objects.create_user(
            username='user1', password='abc123')
        self.user1.save()
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

    def tearDown(self):
        get_user_model().objects.all().delete()
        # Remove credentials
        self.client.credentials()

    def test_create_project(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post(
            '/api/v1/projects/user1/',
            {
                'name': 'api_created_project',
                'description': 'desc',
                'private': True,
            }
        )

        self.assertTrue(status.is_success(response.status_code))

        project = Project.objects.get(name='api_created_project')
        # Will raise exception if it doesn't exist

        self.assertEqual(str(project.owner), 'user1')

    @skip("yet not ready")
    def test_list_public_projects_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.get('/api/v1/projects/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)
        self.assertTrue(
            response.data[0]['name'] in ['test_project1', 'test_project2'])
        self.assertTrue(
            response.data[1]['name'] in ['test_project1', 'test_project2'])

    @skip("yet not ready")
    def test_list_user_projects_api(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        response = self.client.get('/api/v1/projects/test_user1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 3)
