import logging
from datetime import timedelta

from constance import config
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import Organization, Person
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

    def _start_trial(self, account=None):
        return Subscription.create_subscription(
            account or self.subscription.account,
            self.regular_plan,
            self.subscription.created_by,
            timezone.now(),
            start_trial=True,
        )

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

    def test_repointing_the_plan_trial_does_not_affect_running_trials(self):
        other_trial_plan = self._create_plan("pro_trial_v2", is_trial=True)

        self.regular_plan.trial_plan = other_trial_plan
        self.regular_plan.save(update_fields=["trial_plan"])

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.effective_plan, self.trial_plan)

    def test_start_trial_creates_a_single_trial_subscription(self):
        account = self.subscription.account

        subscription = self._start_trial()

        self.assertEqual(
            Subscription.objects.current().filter(account=account).count(), 1
        )
        self.assertEqual(account.current_subscription, subscription)
        self.assertEqual(subscription.plan, self.regular_plan)
        self.assertEqual(subscription.trial_plan, self.trial_plan)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE_TRIAL)
        self.assertEqual(
            subscription.trial_expires_at,
            subscription.active_since + timedelta(days=config.TRIAL_PERIOD_DAYS),
        )
        # The trial has no end date of its own, `trial_expires_at` is what ends it.
        self.assertIsNone(subscription.active_until)
        self.assertTrue(subscription.is_trialing)
        # The trial is granted right away, the payment method is collected later.
        self.assertTrue(subscription.is_active)

    def test_start_trial_closes_the_previous_subscription(self):
        subscription = self._start_trial()

        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status, Subscription.Status.INACTIVE_CANCELLED
        )
        self.assertEqual(self.subscription.active_until, subscription.active_since)

    def test_start_trial_decrements_remaining_trial_organizations(self):
        owner = Person.objects.create(username="owner")
        organization = Organization.objects.create(
            username="org", organization_owner=owner, created_by=owner
        )

        self.assertEqual(owner.remaining_trial_organizations, 1)

        self._start_trial(organization.useraccount)

        owner.refresh_from_db()
        self.assertEqual(owner.remaining_trial_organizations, 0)

    def test_plan_with_a_trial_plan_does_not_start_a_trial_on_its_own(self):
        subscription = Subscription.create_subscription(
            self.subscription.account,
            self.regular_plan,
            self.subscription.created_by,
            timezone.now(),
        )

        self.assertIsNone(subscription.trial_plan)
        self.assertIsNone(subscription.trial_expires_at)
        self.assertFalse(subscription.is_trialing)
        self.assertEqual(
            subscription.status, self.regular_plan.initial_subscription_status
        )
        self.assertEqual(subscription.effective_plan, self.regular_plan)

    def test_start_trial_requires_active_since(self):
        with self.assertRaises(ValueError):
            Subscription.create_subscription(
                self.subscription.account,
                self.regular_plan,
                self.subscription.created_by,
                start_trial=True,
            )

    def test_start_trial_requires_a_plan_with_a_trial_plan(self):
        plan_without_trial = self._create_plan("pro_without_trial")

        with self.assertRaises(ValueError):
            Subscription.create_subscription(
                self.subscription.account,
                plan_without_trial,
                self.subscription.created_by,
                timezone.now(),
                start_trial=True,
            )
