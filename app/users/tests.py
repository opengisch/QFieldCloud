from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


class UsersAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        # Create a user
        test_user1 = get_user_model().objects.create_user(
            username='test_user1', password='abc123', type=1, email='a@b.c')
        test_user1.save()
        cls.token = Token.objects.get_or_create(user=test_user1)[0]

        # Create a second user
        test_user2 = get_user_model().objects.create_user(
            username='test_user2', password='123456', type=1, email='a@b.c')
        test_user2.save()
        cls.token2 = Token.objects.get_or_create(user=test_user2)[0]

    def setUp(self):
        # Remove credentials
        self.client.credentials()

    def tearDown(self):
        # Remove credentials
        self.client.credentials()

    def test_register_user(self):
        response = self.client.post(
            '/api/v1/auth/registration/',
            {
                "username": "pippo",
                "email": "pippo@topolinia.tp",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            }
        )
        self.assertTrue(status.is_success(response.status_code))

    def test_login_session_authentication(self):
        response = self.client.post(
            '/api/v1/auth/login/',
            {
                "username": "test_user1",
                "password": "abc123"
            }
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data['key'], self.token.key)

    def test_login_session_authentication_wrong_password(self):
        response = self.client.post(
            '/api/v1/auth/login/',
            {
                "username": "test_user1",
                "password": "abc1234"
            }
        )
        self.assertTrue(status.is_client_error(response.status_code))
        self.assertFalse('key' in response.data)
