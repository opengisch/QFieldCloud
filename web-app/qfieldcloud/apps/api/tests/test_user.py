from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token


class UserTestCase(APITestCase):

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
        self.assertTrue('key' in response.data)
        self.assertTrue(get_user_model().objects.get(username='pippo'))

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
        self.assertEqual(response.data['key'], token.key)

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
