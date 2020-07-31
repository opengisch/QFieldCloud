import unittest

from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from qfieldcloud.apps.model.models import (
    Organization,
    Project,
    ProjectCollaborator
)


User = get_user_model()


class UserTestCase(APITestCase):
    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(username='user1', password='abc123')
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = User.objects.create_user(username='user2', password='abc123')
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username='organization1',
            password='abc123',
            user_type=2,
            organization_owner=self.user1,
        )

    def test_collaborator_project_takeover(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post(
            '/api/v1/projects/',
            {
                'name': 'beehives',
                'owner': 'user1',
                'description': 'My beehives in Lavertezzo',
                'private': True,
            },
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get('/api/v1/projects/', format='json')
        self.assertEqual(1, len(response.data))
        self.assertEqual('beehives', response.data[0].get('name'))
        project = Project.objects.get(pk=response.data[0].get('id'))

        response = self.client.patch(
            f'/api/v1/projects/{project.pk}/',
            {'name': 'renamed-project', 'owner': 'user1'},
        )
        self.assertTrue(status.is_success(response.status_code))

        # user2 doesn't get to see user1's project
        self.client.logout()

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2.key)
        response = self.client.get('/api/v1/projects/', format='json')
        self.assertEqual(0, len(response.data))

        # user2 is added to the org
        ProjectCollaborator.objects.create(
            project=project, collaborator=self.user2, role=ProjectCollaborator.ROLE_READER
        )
        response = self.client.get('/api/v1/projects/', format='json')
        self.assertEqual(1, len(response.data))
        self.assertEqual('renamed-project', response.data[0].get('name'))

        # patch is denied
        response = self.client.patch(
            f'/api/v1/projects/{project.pk}/',
            {'name': 'stolen-project', 'owner': 'user2'},
        )
        self.assertFalse(status.is_success(response.status_code))
        project.refresh_from_db()
        self.assertEqual('renamed-project', project.name)
