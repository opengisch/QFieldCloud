import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.subscription.models import (
    CurrentSubscription,
    Plan,
    get_subscription_model,
)

logging.disable(logging.CRITICAL)

Subscription = get_subscription_model()


class TrialSubscriptionTestCase(APITransactionTestCase):
    def _create_plan(self, code, *, is_trial=False, storage_mb=1000, **kwargs):
        storage_bytes = storage_mb * 1000 * 1000
        return Plan.objects.create(
            code=code,
            display_name=code,
            is_premium=True,
            is_trial=is_trial,
            storage_mb=storage_mb,
            storage_threshold_warning_bytes=int(storage_bytes * 0.20),
            storage_threshold_critical_bytes=int(storage_bytes * 0.10),
            **kwargs,
        )

    def _expire_trial(self):
        self.subscription.trial_expires_at = timezone.now() - timedelta(seconds=1)
        self.subscription.save(update_fields=["trial_expires_at"])

    def setUp(self):
        setup_subscription_plans()

        # Regular plan is larger than its trial plan
        self.trial_plan = self._create_plan("pro_trial", is_trial=True, storage_mb=1000)
        self.regular_plan = self._create_plan(
            "pro", storage_mb=5000, trial_plan=self.trial_plan
        )

        self.subscription = Person.objects.create(
            username="user1"
        ).useraccount.current_subscription
        self.subscription.plan = self.regular_plan
        self.subscription.trial_plan = self.trial_plan
        self.subscription.trial_expires_at = timezone.now() + timedelta(days=5)
        self.subscription.status = Subscription.Status.ACTIVE_TRIAL
        self.subscription.active_since = timezone.now() - timedelta(days=1)
        self.subscription.save()

    def test_active_trial_grants_access_until_it_expires(self):
        self.assertTrue(Subscription.objects.get(pk=self.subscription.pk).is_active)

        self._expire_trial()

        # Still ACTIVE_TRIAL and in-period, but access stops once expired.
        self.assertFalse(Subscription.objects.get(pk=self.subscription.pk).is_active)

    def test_trial_uses_trial_plan_limits_until_it_expires(self):
        self.assertEqual(self.subscription.effective_plan, self.trial_plan)
        self.assertEqual(
            self.subscription.included_storage_bytes, self.trial_plan.storage_bytes
        )

        self._expire_trial()

        self.assertEqual(self.subscription.effective_plan, self.regular_plan)
        self.assertEqual(
            self.subscription.included_storage_bytes, self.regular_plan.storage_bytes
        )

    def test_current_subscription_view_resolves_the_effective_plan(self):
        account_id = self.subscription.account_id

        current = CurrentSubscription.objects.get(account_id=account_id)
        self.assertEqual(current.plan, self.trial_plan)

        self._expire_trial()

        current = CurrentSubscription.objects.get(account_id=account_id)
        self.assertEqual(current.plan, self.regular_plan)
