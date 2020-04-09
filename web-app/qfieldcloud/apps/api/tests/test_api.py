from django.contrib.auth import get_user_model
from django.conf import settings

from rest_framework import status
from rest_framework.test import APITransactionTestCase

User = get_user_model()
# Use a different PROJECTS_ROOT for the tests
settings.PROJECTS_ROOT += '_test'


class StatusTestCase(APITransactionTestCase):

    def test_api_status(self):
        response = self.client.get('/api/v1/status/')
        self.assertTrue(status.is_success(response.status_code))
