from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token

from qfieldcloud.apps.model.models import (
    Organization, OrganizationMember)


class UserTestCase(APITestCase):

    def setUp(self):
        # Create a user
        self.user1 = get_user_model().objects.create_user(
            username='user1', password='abc123')
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = get_user_model().objects.create_user(
            username='user2', password='abc123')
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username='organization1', password='abc123',
            user_type=2, organization_owner=self.user1)

        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1, member=self.user2,
            role=OrganizationMember.ROLE_MEMBER).save()

    def tearDown(self):
        get_user_model().objects.all().delete()
        Organization.objects.all().delete()
        # Remove credentials
        self.client.credentials()

    def test_register_user(self):
        response = self.client.post(
            '/api/v1/auth/registration/',
            {
                "username": "pippo",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            }
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue('token' in response.data)
        self.assertTrue(get_user_model().objects.get(username='pippo'))

    def test_register_user_reserved_word(self):
        response = self.client.post(
            '/api/v1/auth/registration/',
            {
                "username": "user",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login(self):
        # Create a user
        pippo = get_user_model().objects.create_user(
            username='pippo', password='abc123')
        pippo.save()

        # Get the user's token
        token = Token.objects.get_or_create(user=pippo)[0]

        response = self.client.post(
            '/api/v1/auth/login/',
            {
                "username": "pippo",
                "password": "abc123"
            }
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['token'], token.key)
        self.assertEqual(response.data['user'], 'pippo')

    def test_login_wrong_password(self):
        # Create a user
        pippo = get_user_model().objects.create_user(
            username='pippo', password='abc123')
        pippo.save()

        response = self.client.post(
            '/api/v1/auth/login/',
            {
                "username": "pippo",
                "password": "1234"
            }
        )
        self.assertTrue(status.is_client_error(response.status_code))
        self.assertFalse('key' in response.data)

    def test_get_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.get('/api/v1/users/user1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['username'], 'user1')
        self.assertEqual(response.data['user_type'], 1)
        self.assertTrue('email' in response.json())

    def test_get_another_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.get('/api/v1/users/user2/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['username'], 'user2')
        self.assertEqual(response.data['user_type'], 1)
        self.assertFalse('email' in response.json())

    def test_get_organization(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.get('/api/v1/users/organization1/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['username'], 'organization1')
        self.assertEqual(response.data['user_type'], 2)
        self.assertEqual(response.data['organization_owner'], 'user1')
        self.assertEqual(len(response.data['members']), 1)

    def test_list_users(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.get('/api/v1/users/')

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k['username'])

        self.assertEqual(json[0]['username'], 'organization1')
        self.assertEqual(json[1]['username'], 'user1')
        self.assertEqual(json[2]['username'], 'user2')

    def test_get_the_authenticated_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.get('/api/v1/users/user/')

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['username'], 'user1')
        self.assertEqual(response.data['user_type'], 1)
        self.assertTrue('email' in response.json())

    def test_update_the_authenticated_user(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)

        response = self.client.patch('/api/v1/users/user/',
                                     {
                                         'first_name': 'Charles',
                                         'last_name': 'Darwin',
                                         'email': 'charles@beagle.uk',
                                     })

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['username'], 'user1')
        self.assertEqual(response.data['user_type'], 1)
        self.assertEqual(response.data['first_name'], 'Charles')
        self.assertEqual(response.data['last_name'], 'Darwin')
        self.assertEqual(response.data['email'], 'charles@beagle.uk')

    def test_logout(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post('/api/v1/auth/logout/')
        self.assertTrue(status.is_success(response.status_code))

        # The token should not work anymore
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get('/api/v1/users/user/')
        self.assertFalse(status.is_success(response.status_code))

    def test_api_token_auth(self):
        response = self.client.post(
            '/api/v1/auth/token/',
            {
                "username": "user1",
                "password": "abc123"
            }
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['token'], self.token1.key)
        self.assertEqual(response.data['user'], 'user1')

    def test_api_token_auth_after_logout(self):
        response = self.client.post(
            '/api/v1/auth/token/',
            {
                "username": "user1",
                "password": "abc123"
            }
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['token'], self.token1.key)
        self.assertEqual(response.data['user'], 'user1')

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.post('/api/v1/auth/logout/')
        self.assertTrue(status.is_success(response.status_code))

        # Remove the old token from the headers
        self.client.credentials()

        response = self.client.post(
            '/api/v1/auth/token/',
            {
                "username": "user1",
                "password": "abc123"
            }
        )

        self.assertTrue(status.is_success(response.status_code))
        # The token should be different from before
        self.assertNotEqual(response.data['token'], self.token1.key)
        self.assertEqual(response.data['user'], 'user1')
