from django.core.exceptions import ValidationError
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.tests.utils import setup_subscription_plans

from ..models import Plan


class QfcTestCase(APITransactionTestCase):
    """Tests for Plan.storage_threshold_warning_bytes/critical_bytes validation."""

    def setUp(self):
        setup_subscription_plans()

    def test_plan_storage_threshold_validation(self):
        plan = Plan.objects.first()

        # update storage_threshold_warning_bytes to 0
        plan.storage_threshold_warning_bytes = 0
        plan.storage_threshold_critical_bytes = 0
        with self.assertRaisesRegex(ValidationError, "must be greater than 0."):
            plan.save()

        # update storage_threshold_critical_bytes to be greater than storage_threshold_warning_bytes
        plan.refresh_from_db()
        plan.storage_threshold_critical_bytes = plan.storage_threshold_warning_bytes + 1
        with self.assertRaisesRegex(
            ValidationError, "must be less than storage_threshold_warning_bytes"
        ):
            plan.save()

        # update storage_threshold_warning_bytes to be greater than storage_mb
        plan.refresh_from_db()
        plan.storage_threshold_warning_bytes = plan.storage_bytes + 1
        with self.assertRaisesRegex(ValidationError, "must be less than storage_mb"):
            plan.save()
