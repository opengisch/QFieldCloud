import logging
from datetime import timedelta

import django.db.utils
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Organization, Person, Project
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans

from ..exceptions import NotPremiumPlanException
from ..models import Package, PackageType, Plan, get_subscription_model

logging.disable(logging.CRITICAL)

Subscription = get_subscription_model()


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()
        PackageType.get_storage_package_type.cache_clear()

    def test_useraccount_gets_current_subscription(self):
        u1 = Person.objects.create(username="u1")

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(
            Subscription.objects.first(), u1.useraccount.current_subscription
        )

    def test_subscription_periods_overlap_is_prevented(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        with self.assertRaises(django.core.exceptions.ValidationError):
            Subscription.objects.create(
                plan=Plan.get_or_create_default(),
                account=u1.useraccount,
                created_by=u1,
                status=Subscription.Status.ACTIVE_PAID,
                active_since=timezone.now(),
            )

        self.assertEqual(u1.useraccount.current_subscription, subscription)

    def test_active_storage_total_mb(self):
        """Test property has correct values in cases of no packages, with active package, and rewrite of the active package"""
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.active_storage_total_mb, 1)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.active_storage_total_mb, 2001)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(subscription.active_storage_total_mb, 3001)

    def test_active_storage_package(self):
        """Test property has correct values in cases of no packages, with active package, and rewrite of the active package"""
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertIsNone(subscription.active_storage_package)

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.active_storage_package, new)

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(subscription.active_storage_package, new)

    def test_active_storage_package_quantity(self):
        """Test property has correct values in cases of no packages, with active package, and rewrite of the active package"""
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.active_storage_package_quantity, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.active_storage_package_quantity, 2)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(subscription.active_storage_package_quantity, 3)

    def test_active_storage_package_mb(self):
        """Test property has correct values in cases of no packages, with active package, and rewrite of the active package"""
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.active_storage_package_mb, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.active_storage_package_mb, 2000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(subscription.active_storage_package_mb, 3000)

    def test_future_storage_total_mb(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.future_storage_package_mb, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.future_storage_package_mb, 2000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(subscription.future_storage_package_mb, 3000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package_mb, 4000)

    def test_future_storage_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertIsNone(subscription.future_storage_package)

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertIsNone(subscription.future_storage_package)

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(subscription.future_storage_package, new)

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package, new)

    def test_future_storage_package_quantity(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.future_storage_package_quantity, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.future_storage_package_quantity, 2)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(subscription.future_storage_package_quantity, 3)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package_quantity, 4)

    def test_future_storage_package_mb(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.future_storage_package_mb, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(subscription.future_storage_package_mb, 2000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(subscription.future_storage_package_mb, 3000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package_mb, 4000)

    def test_future_storage_package_changed_mb(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        self.assertEqual(subscription.future_storage_package_changed_mb, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 1
        )

        self.assertEqual(subscription.future_storage_package_changed_mb, 0)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(subscription.future_storage_package_changed_mb, 2000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package_changed_mb, 3000)

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            0,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(subscription.future_storage_package_changed_mb, -1000)

    def test_get_active_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        self.assertIsNone(
            subscription.get_active_package(PackageType.get_storage_package_type())
        )

        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )
        self.assertIsNone(
            subscription.get_active_package(PackageType.get_storage_package_type())
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(
            subscription.get_active_package(PackageType.get_storage_package_type()), new
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(
            subscription.get_active_package(PackageType.get_storage_package_type()), new
        )

    def test_get_active_package_quantity(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        self.assertEqual(
            subscription.get_active_package_quantity(
                PackageType.get_storage_package_type()
            ),
            0,
        )

        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )
        self.assertEqual(
            subscription.get_active_package_quantity(
                PackageType.get_storage_package_type()
            ),
            0,
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(
            subscription.get_active_package_quantity(
                PackageType.get_storage_package_type()
            ),
            2,
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 3
        )

        self.assertEqual(
            subscription.get_active_package_quantity(
                PackageType.get_storage_package_type()
            ),
            3,
        )

    def test_get_future_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        self.assertIsNone(
            subscription.get_future_package(PackageType.get_storage_package_type())
        )

        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )
        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertIsNone(
            subscription.get_future_package(PackageType.get_storage_package_type())
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(
            subscription.get_future_package(PackageType.get_storage_package_type()), new
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(
            subscription.get_future_package(PackageType.get_storage_package_type()), new
        )

    def test_get_future_package_quantity(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        self.assertEqual(
            subscription.get_future_package_quantity(
                PackageType.get_storage_package_type()
            ),
            0,
        )

        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )
        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertEqual(
            subscription.get_future_package_quantity(
                PackageType.get_storage_package_type()
            ),
            2,
        )

        _old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            3,
            timezone.now() + timedelta(days=1),
        )

        self.assertEqual(
            subscription.get_future_package_quantity(
                PackageType.get_storage_package_type()
            ),
            3,
        )

        _old, _new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            4,
            timezone.now() + timedelta(days=5),
        )

        self.assertEqual(
            subscription.get_future_package_quantity(
                PackageType.get_storage_package_type()
            ),
            4,
        )

    def test_set_package_quantity(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        # no packages exist
        self.assertEqual(Package.objects.count(), 0)

        # one package that will be created with quantity 2
        subscription.set_package_quantity(PackageType.get_storage_package_type(), 2)

        self.assertEqual(Package.objects.count(), 1)
        self.assertEqual(Package.objects.latest("created_at").quantity, 2)
        self.assertEqual(
            Package.objects.latest("created_at").type,
            PackageType.get_storage_package_type(),
        )

        # the old package will expire and a new one is created with quantity 3
        subscription.set_package_quantity(PackageType.get_storage_package_type(), 3)

        self.assertEqual(Package.objects.count(), 2)
        self.assertEqual(Package.objects.latest("created_at").quantity, 3)
        self.assertEqual(
            Package.objects.latest("created_at").type,
            PackageType.get_storage_package_type(),
        )

    def test_set_package_quantity_raises_on_non_premium_plan(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        with self.assertRaises(NotPremiumPlanException):
            subscription.set_package_quantity(PackageType.get_storage_package_type(), 2)

    def test_set_package_quantity_with_existing_active_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        created_package = Package.objects.create(
            subscription=u1.useraccount.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
        )

        old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            2,
        )

        self.assertNotEqual(old, new)
        self.assertEqual(old, created_package)
        self.assertEqual(subscription.packages.count(), 2)
        self.assertIsNotNone(new.active_since)
        self.assertEqual(new.active_since, old.active_until)
        self.assertIsNone(new.active_until)

    def test_set_package_quantity_with_existing_expired_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        created_package = Package.objects.create(
            subscription=u1.useraccount.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
            active_until=timezone.now() - timedelta(days=2),
        )

        old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )

        self.assertIsNone(old)
        self.assertNotEqual(old, new)
        self.assertNotEqual(new, created_package)
        self.assertEqual(subscription.packages.count(), 2)
        self.assertIsNotNone(new.active_since)
        self.assertIsNone(new.active_until)

    def test_set_package_quantity_with_existing_future_package(self):
        u1 = Person.objects.create(username="u1")
        subscription = set_subscription(
            u1,
            storage_mb=1,
            is_premium=True,
        )

        created_package = Package.objects.create(
            subscription=u1.useraccount.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() + timedelta(days=2),
        )

        old, new = subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 2
        )
        self.assertIsNone(old)
        self.assertNotEqual(old, new)
        self.assertNotEqual(new, created_package)
        self.assertEqual(subscription.packages.count(), 1)
        self.assertIsNotNone(new.active_since)
        self.assertIsNone(new.active_until)

    def test_update_subscription(self):
        u1 = Person.objects.create(username="u1")
        subscription = u1.useraccount.current_subscription

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE_PAID)

        requested_cancel_at = timezone.now() + timedelta(days=10)
        subscription = Subscription.update_subscription(
            subscription,
            status=Subscription.Status.ACTIVE_PAST_DUE,
            requested_cancel_at=requested_cancel_at,
        )

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE_PAST_DUE)
        self.assertEqual(subscription.requested_cancel_at, requested_cancel_at)

    def test_get_or_create_current_subscription_when_already_exists(self):
        u1 = Person.objects.create(username="u1")
        plan = Plan.objects.get(
            user_type=u1.useraccount.user.type,
            is_default=True,
        )

        # already exists by default
        self.assertEqual(Subscription.objects.count(), 1)

        Subscription.objects.all().delete()

        self.assertEqual(Subscription.objects.count(), 0)

        created_subscription = Subscription.objects.create(
            plan=plan,
            account=u1.useraccount,
            created_by=u1,
            status=Subscription.Status.ACTIVE_PAID,
            active_since=timezone.now(),
        )

        self.assertEqual(Subscription.objects.count(), 1)

        found_subscription = Subscription.get_or_create_current_subscription(
            u1.useraccount
        )

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(created_subscription, found_subscription)
        self.assertEqual(found_subscription, u1.useraccount.current_subscription)

    def test_get_or_create_current_subscription_when_subscription_expired(self):
        u1 = Person.objects.create(username="u1")
        plan = Plan.objects.get(
            user_type=u1.useraccount.user.type,
            is_default=True,
        )

        # already exists by default
        self.assertEqual(Subscription.objects.count(), 1)

        Subscription.objects.all().delete()

        self.assertEqual(Subscription.objects.count(), 0)

        created_subscription = Subscription.objects.create(
            plan=plan,
            account=u1.useraccount,
            created_by=u1,
            status=Subscription.Status.ACTIVE_PAID,
            active_since=timezone.now() - timedelta(days=60),
            active_until=timezone.now() - timedelta(days=30),
        )

        self.assertEqual(Subscription.objects.count(), 1)

        found_subscription = Subscription.get_or_create_current_subscription(
            u1.useraccount
        )

        self.assertEqual(Subscription.objects.count(), 2)
        self.assertNotEqual(created_subscription, found_subscription)
        self.assertEqual(found_subscription, u1.useraccount.current_subscription)

    def test_get_or_create_current_subscription_when_no_subscription_exists(self):
        u1 = Person.objects.create(username="u1")

        # already exists by default
        self.assertEqual(Subscription.objects.count(), 1)

        Subscription.objects.all().delete()

        self.assertEqual(Subscription.objects.count(), 0)

        found_subscription = Subscription.get_or_create_current_subscription(
            u1.useraccount
        )

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(found_subscription, u1.useraccount.current_subscription)

    def test_create_default_plan_subscription(self):
        u1 = Person.objects.create(username="u1")

        # the subscription is created anyway
        self.assertEqual(Subscription.objects.count(), 1)
        # so delete it
        Subscription.objects.all().delete()
        self.assertEqual(Subscription.objects.count(), 0)

        subscription = Subscription.create_default_plan_subscription(u1.useraccount)

        self.assertEqual(Subscription.objects.count(), 1)
        self.assertEqual(subscription.account, u1.useraccount)
        self.assertIsNotNone(subscription.active_since)
        self.assertIsNone(subscription.active_until)

    def test_create_default_plan_subscription_raises_when_subscription_already_exists(
        self,
    ):
        u1 = Person.objects.create(username="u1")

        # the subscription is created anyway
        self.assertEqual(Subscription.objects.count(), 1)

        with self.assertRaises(django.db.utils.IntegrityError):
            Subscription.create_default_plan_subscription(u1.useraccount)

    def test_remaining_trial_organizations_is_set_and_decremented(
        self,
    ):
        user_plan = Plan.objects.get(code="default_user")
        user_plan.max_trial_organizations = 2
        user_plan.save(update_fields=["max_trial_organizations"])
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")

        # remaining_trial_organizations is set on create_subscription
        self.assertEqual(u1.remaining_trial_organizations, 2)
        self.assertEqual(u2.remaining_trial_organizations, 2)

        trial_plan = Plan.objects.get(code="default_org")
        trial_plan.is_trial = True
        trial_plan.save(update_fields=["is_trial"])

        # remaining_trial_organizations is decremented for owner when creating a trial organization
        Organization.objects.create(
            username="org2", organization_owner=u2, created_by=u1
        )
        u2.refresh_from_db()
        self.assertEqual(u2.remaining_trial_organizations, 1)
        u1.refresh_from_db()
        self.assertEqual(u1.remaining_trial_organizations, 2)

        # remaining_trial_organizations is decremented down to 0
        Organization.objects.create(
            username="org3", organization_owner=u2, created_by=u1
        )
        u2.refresh_from_db()
        self.assertEqual(u2.remaining_trial_organizations, 0)

        # It doesn't directly prevent creating more trials, is just a counter that stays at 0
        Organization.objects.create(
            username="org4", organization_owner=u2, created_by=u1
        )
        u2.refresh_from_db()
        self.assertEqual(u2.remaining_trial_organizations, 0)

        # NOTE changing ownership does not affect the `remaining_trial_organizations` and is not tested

    def test_project_lists_duplicates_if_multiple_subscriptions(self):
        u1 = Person.objects.create(username="u1")
        old_subscription = u1.useraccount.current_subscription
        old_subscription.active_since -= timedelta(days=1)
        old_subscription.active_until = timezone.now().replace(microsecond=0)
        old_subscription.save()

        Project.objects.create(name="p1", owner=u1)

        count = Project.objects.for_user(u1).count()

        new_subscription = u1.useraccount.current_subscription

        self.assertEqual(count, 1)
        self.assertNotEqual(old_subscription, new_subscription)

        count = Project.objects.for_user(u1).count()

        self.assertEqual(count, 1)
