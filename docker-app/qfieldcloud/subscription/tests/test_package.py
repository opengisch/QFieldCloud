import logging

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.tests.utils import setup_subscription_plans
from rest_framework.test import APITransactionTestCase

from ..models import PackageType

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()

    def test_get_storage_package_type(self):
        package_type = PackageType.objects.create(
            unit_amount=1,
            code="storage_package",
            type=PackageType.Type.STORAGE,
            min_quantity=0,
            max_quantity=100,
        )

        self.assertEqual(PackageType.get_storage_package_type(), package_type)
