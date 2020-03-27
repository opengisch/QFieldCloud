from unittest import skip

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import (
    Project, ProjectCollaborator)

User = get_user_model()


class ProjectTestCase(APITestCase):

    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(
            username='user1', password='abc123')
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a user
        self.user2 = User.objects.create_user(
            username='user2', password='abc123')
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create a user
        self.user3 = User.objects.create_user(
            username='user3', password='abc123')
        self.token3 = Token.objects.get_or_create(user=self.user3)[0]

    def tearDown(self):
        User.objects.all().delete()
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

        # Create a public project of user2
        self.project1 = Project.objects.create(
            name='project1',
            private=False,
            owner=self.user2)

        # Create a private project of user2
        self.project1 = Project.objects.create(
            name='project2',
            private=True,
            owner=self.user2)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/projects/?include-public=true')
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'project1')
        self.assertEqual(response.data[0]['owner'], 'user2')

    def test_list_projects_of_specific_user(self):

        # Create a project
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Create a project
        self.project1 = Project.objects.create(
            name='project2',
            private=True,
            owner=self.user1)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/projects/user1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 2)

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(json[0]['name'], 'project1')
        self.assertEqual(json[0]['owner'], 'user1')
        self.assertEqual(json[1]['name'], 'project2')
        self.assertEqual(json[0]['owner'], 'user1')

    def test_list_collaborators_of_project(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.ROLE_MANAGER)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get(
            '/api/v1/collaborators/user1/project1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 1)

        json = response.json()
        json = sorted(json, key=lambda k: k['collaborator'])

        self.assertEqual(json[0]['collaborator'], 'user2')
        self.assertEqual(json[0]['role'], 'manager')

    def test_list_projects_of_authenticated_user(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Create another project of user1
        self.project2 = Project.objects.create(
            name='project2',
            private=True,
            owner=self.user1)

        # Create a project of user2 without access to user1
        self.project3 = Project.objects.create(
            name='project3',
            private=True,
            owner=self.user2)

        # Create a project of user2 with access to user1
        self.project4 = Project.objects.create(
            name='project4',
            private=True,
            owner=self.user2)

        ProjectCollaborator.objects.create(
            project=self.project4,
            collaborator=self.user1,
            role=ProjectCollaborator.ROLE_MANAGER)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/projects/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.data), 3)

        json = response.json()
        json = sorted(json, key=lambda k: k['name'])

        self.assertEqual(json[0]['name'], 'project1')
        self.assertEqual(json[0]['owner'], 'user1')
        self.assertEqual(json[1]['name'], 'project2')
        self.assertEqual(json[1]['owner'], 'user1')
        self.assertEqual(json[2]['name'], 'project4')
        self.assertEqual(json[2]['owner'], 'user2')

    def test_create_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post(
            '/api/v1/collaborators/user1/project1/',
            {
                'collaborator': 'user2',
                'role': 'editor',
            }
        )
        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 1)
        self.assertEqual(collaborators[0].project, self.project1)
        self.assertEqual(collaborators[0].collaborator, self.user2)
        self.assertEqual(
            collaborators[0].role, ProjectCollaborator.ROLE_EDITOR)

    def test_get_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.ROLE_REPORTER)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get(
            '/api/v1/collaborators/user1/project1/user2/')

        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        self.assertEqual(json['collaborator'], 'user2')
        self.assertEqual(json['role'], 'reporter')

    def test_update_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.ROLE_REPORTER)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.patch(
            '/api/v1/collaborators/user1/project1/user2/',
            {
                'role': 'admin',
            }
        )

        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 1)
        self.assertEqual(collaborators[0].project, self.project1)
        self.assertEqual(collaborators[0].collaborator, self.user2)
        self.assertEqual(
            collaborators[0].role, ProjectCollaborator.ROLE_ADMIN)

    def test_delete_collaborator(self):

        # Create a project of user1
        self.project1 = Project.objects.create(
            name='project1',
            private=True,
            owner=self.user1)

        # Add user2 as collaborator
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.ROLE_REPORTER)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.delete(
            '/api/v1/collaborators/user1/project1/user2/')

        self.assertTrue(status.is_success(response.status_code))

        collaborators = ProjectCollaborator.objects.all()
        self.assertEqual(len(collaborators), 0)
