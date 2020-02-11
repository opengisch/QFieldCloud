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

    def test_create_project_reserved_name(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post(
            '/api/v1/projects/user1/',
            {
                'name': 'project',
                'description': 'desc',
                'private': True,
            }
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_public_projects(self):

        # Create a public project
        self.project1 = Project.objects.create(
            name='project1',
            private=False,
            owner=self.user1)
        self.project1.save()

        # Create a private project
        self.project1 = Project.objects.create(
            name='project2',
            private=True,
            owner=self.user1)
        self.project1.save()

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/projects/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'project1')

    def test_list_user_projects(self):

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)
        self.project1.save()

        # Create a project
        self.project1 = Project.objects.create(
            name='project2',
            private=True,
            owner=self.user1)
        self.project1.save()

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/projects/user1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(json[0]['name'], 'project1')
        self.assertEqual(json[1]['name'], 'project2')
