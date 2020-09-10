from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.test import APITransactionTestCase

User = get_user_model()


class StatusTestCase(APITransactionTestCase):

    def test_api_status(self):
        response = self.client.get('/api/v1/status/')
        self.assertTrue(status.is_success(response.status_code))
        self.assertIn(response.json()['orchestrator'], ['ok', 'slow'])
        self.assertEqual(response.json()['redis'], 'ok')
        self.assertEqual(response.json()['storage'], 'ok')
