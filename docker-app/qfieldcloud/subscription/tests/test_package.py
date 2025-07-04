import logging
from datetime import timedelta

import django.db.utils
from django.utils import timezone
from django_currentuser.middleware import _set_current_user
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.tests.utils import get_random_file, setup_subscription_plans

from ..exceptions import NotPremiumPlanException
from ..models import Package, PackageType, Plan

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()

        self.u1 = Person.objects.create(username="u1")
        self.a1 = self.u1.useraccount

        # NOTE since we do not login via the API, the django_currentuser module is unable to set
        # the current user from the request object. Therefore the user set from another test
        # remains in the internal django_currentuser cache and causes the test to fail. So we have
        # to manually reset the current user to None.
        _set_current_user(None)

        self.plan_default = Plan.get_or_create_default()
        self.plan_premium = Plan.objects.create(
            code="plan_1mb",
            storage_mb=1,
            is_premium=True,
        )

        # need to clean the `lru_cache` value since we recreate the PackageType for each test
        PackageType.get_storage_package_type.cache_clear()

        subscription = self.a1.current_subscription
        subscription.plan = self.plan_premium
        subscription.save()

    def assertStorage(
        self,
        active_storage_total_mb,
        active_storage_package,
        active_storage_package_quantity,
        active_storage_package_mb,
        future_storage_total_mb,
        future_storage_package,
        future_storage_package_quantity,
        future_storage_package_mb,
        future_storage_package_changed_mb,
        storage_used_mb,
        storage_free_mb,
        user=None,
    ):
        if user is None:
            user = self.u1

        self.assertEqual(
            user.useraccount.current_subscription.active_storage_total_mb,
            active_storage_total_mb,
        )
        self.assertEqual(
            user.useraccount.current_subscription.active_storage_package,
            active_storage_package,
        )
        self.assertEqual(
            user.useraccount.current_subscription.active_storage_package_quantity,
            active_storage_package_quantity,
        )
        self.assertEqual(
            user.useraccount.current_subscription.active_storage_package_mb,
            active_storage_package_mb,
        )
        self.assertEqual(
            user.useraccount.current_subscription.future_storage_total_mb,
            future_storage_total_mb,
        )
        self.assertEqual(
            user.useraccount.current_subscription.future_storage_package,
            future_storage_package,
        )
        self.assertEqual(
            user.useraccount.current_subscription.future_storage_package_quantity,
            future_storage_package_quantity,
        )
        self.assertEqual(
            user.useraccount.current_subscription.future_storage_package_mb,
            future_storage_package_mb,
        )
        self.assertEqual(
            user.useraccount.current_subscription.future_storage_package_changed_mb,
            future_storage_package_changed_mb,
        )
        self.assertEqual(
            user.useraccount.storage_used_bytes, storage_used_mb * 1000 * 1000
        )
        self.assertEqual(
            user.useraccount.storage_free_bytes, storage_free_mb * 1000 * 1000
        )

    def test_get_storage_package_type(self):
        PackageType.objects.all().delete()
        PackageType.get_storage_package_type.cache_clear()

        package_type = PackageType.objects.create(
            unit_amount=1,
            code="test_storage_package",
            type=PackageType.Type.STORAGE,
            min_quantity=0,
            max_quantity=100,
        )

        self.assertEqual(PackageType.get_storage_package_type().pk, package_type.pk)

    def test_storage_on_default_plan(self):
        subscription = self.a1.current_subscription
        subscription.plan = self.plan_default
        subscription.save()

        self.assertStorage(
            active_storage_total_mb=self.plan_default.storage_mb,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=self.plan_default.storage_mb,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=self.plan_default.storage_mb,
        )

    def test_default_plan_raises_when_adding_active_storage(self):
        subscription = self.a1.current_subscription
        subscription.plan = self.plan_default
        subscription.save()

        with self.assertRaises(NotPremiumPlanException):
            self.a1.current_subscription.set_package_quantity(
                PackageType.get_storage_package_type(), 1
            )

        self.assertStorage(
            active_storage_total_mb=self.plan_default.storage_mb,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=self.plan_default.storage_mb,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=self.plan_default.storage_mb,
        )

    def test_default_plan_ignores_active_package(self):
        subscription = self.a1.current_subscription
        subscription.plan = self.plan_default
        subscription.save()

        Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
            active_until=timezone.now() + timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=self.plan_default.storage_mb,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=self.plan_default.storage_mb,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=self.plan_default.storage_mb,
        )

    def test_premium_plan_without_additional_storage(self):
        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1,
        )

    def test_premium_plan_with_active_storage(self):
        package = Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
            active_until=timezone.now() + timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=-1000,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_premium_plan_with_active_storage_without_end_date(self):
        package = Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
            active_until=None,
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_premium_plan_with_expired_storage(self):
        Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() - timedelta(days=3),
            active_until=timezone.now() - timedelta(days=2),
        )

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1,
        )

    def test_premium_plan_with_future_storage(self):
        package = Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=timezone.now() + timedelta(days=2),
            active_until=timezone.now() + timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1001,
            future_storage_package=package,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=1000,
            storage_used_mb=0,
            storage_free_mb=1,
        )

    def test_premium_plan_with_active_and_future_and_expired_storage(self):
        now = timezone.now()
        active_package = Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=now - timedelta(days=3),
            active_until=now + timedelta(days=3),
        )
        Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=now - timedelta(days=5),
            active_until=now - timedelta(days=3),
        )
        future_package = Package.objects.create(
            subscription=self.a1.current_subscription,
            type=PackageType.get_storage_package_type(),
            quantity=1,
            active_since=now + timedelta(days=3),
            active_until=now + timedelta(days=5),
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=active_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=future_package,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_premium_plan_can_add_active_storage(self):
        _old_package, new_package = self.a1.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 1
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=new_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_premium_plan_can_add_active_storage_with_quantity_of_42(self):
        _old_package, new_package = self.a1.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 42
        )

        self.assertStorage(
            active_storage_total_mb=42001,
            active_storage_package=new_package,
            active_storage_package_quantity=42,
            active_storage_package_mb=42000,
            future_storage_total_mb=42001,
            future_storage_package=None,
            future_storage_package_quantity=42,
            future_storage_package_mb=42000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=42001,
        )

    def test_premium_plan_can_add_future_storage(self):
        _old_package, new_package = self.a1.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            1,
            timezone.now() + timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1001,
            future_storage_package=new_package,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=1000,
            storage_used_mb=0,
            storage_free_mb=1,
        )

    def test_premium_plan_can_replace_active_storage(self):
        (
            old_package,
            active_package,
        ) = self.a1.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 1
        )

        self.assertIsNone(old_package)
        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=active_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

        (
            retired_package,
            future_package,
        ) = self.a1.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(),
            2,
            timezone.now() + timedelta(days=3),
        )

        self.assertEqual(active_package, retired_package)
        self.assertEqual(retired_package.active_until, future_package.active_since)

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=retired_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=2001,
            future_storage_package=future_package,
            future_storage_package_quantity=2,
            future_storage_package_mb=2000,
            future_storage_package_changed_mb=1000,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_storage_with_custom_additional_storage(self):
        PackageType.objects.all().delete()
        PackageType.get_storage_package_type.cache_clear()
        package_type = PackageType.objects.create(
            unit_amount=2,
            code="extra_2mb",
            type=PackageType.Type.STORAGE,
            min_quantity=0,
            max_quantity=100,
        )

        self.assertEqual(package_type.pk, PackageType.get_storage_package_type().pk)

        _old_package, new_package = self.a1.current_subscription.set_package_quantity(
            package_type,
            1,
        )

        self.assertStorage(
            active_storage_total_mb=3,
            active_storage_package=new_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=2,
            future_storage_total_mb=3,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=2,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=3,
        )

    def test_storage_cannot_have_packages_with_time_overlaps(self):
        subscription = self.u1.useraccount.current_subscription
        package = Package.objects.create(
            subscription=subscription,
            quantity=1,
            type=PackageType.get_storage_package_type(),
            active_since=timezone.now() - timedelta(days=3),
            active_until=timezone.now() + timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=-1000,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

        with self.assertRaises(django.db.utils.IntegrityError):
            Package.objects.create(
                subscription=subscription,
                quantity=2,
                type=PackageType.get_storage_package_type(),
                active_since=timezone.now() - timedelta(days=2),
                active_until=timezone.now() + timedelta(days=6),
            )

        # Nothing changed
        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=-1000,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_storage_cannot_add_new_package_when_active_until_is_null(self):
        subscription = self.u1.useraccount.current_subscription
        package = Package.objects.create(
            subscription=subscription,
            quantity=1,
            type=PackageType.get_storage_package_type(),
            active_since=timezone.now() - timedelta(days=3),
        )

        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

        with self.assertRaises(django.db.utils.IntegrityError):
            Package.objects.create(
                subscription=subscription,
                quantity=2,
                type=PackageType.get_storage_package_type(),
                active_since=timezone.now() - timedelta(days=2),
            )

        # Nothing changed
        self.assertStorage(
            active_storage_total_mb=1001,
            active_storage_package=package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1001,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1001,
        )

    def test_used_storage_changes_when_uploading_and_deleting_files_and_versions(self):
        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1,
        )

        p1 = Project.objects.create(name="p1", owner=self.u1)
        token = AuthToken.objects.get_or_create(user=self.u1)[0]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        response = self.client.post(
            f"/api/v1/files/{p1.id}/file.name/",
            {"file": get_random_file(mb=0.3)},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        p1.save(recompute_storage=True)

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0.3,
            storage_free_mb=0.7,
        )

        response = self.client.post(
            f"/api/v1/files/{p1.id}/file.name/",
            {"file": get_random_file(mb=0.1)},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        p1.save(recompute_storage=True)

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0.4,
            storage_free_mb=0.6,
        )

        # TODO Delete with QF-4963 Drop support for legacy storage
        if p1.uses_legacy_storage:
            version = p1.legacy_files[0].versions[0]
        else:
            version = p1.project_files[0].versions.all().reverse()[0]

        response = self.client.delete(
            f"/api/v1/files/{p1.id}/file.name/?version={str(version.id)}",
        )

        # TODO Delete with QF-4963 Drop support for legacy storage
        if p1.uses_legacy_storage:
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        else:
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        p1.save(recompute_storage=True)

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0.1,
            storage_free_mb=0.9,
        )

        response = self.client.delete(f"/api/v1/files/{p1.id}/file.name/")

        # TODO Delete with QF-4963 Drop support for legacy storage
        if p1.uses_legacy_storage:
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        else:
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        p1.save(recompute_storage=True)

        self.assertStorage(
            active_storage_total_mb=1,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=1,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1,
        )

    def test_api_enforces_storage_limit(self):
        p1 = Project.objects.create(name="p1", owner=self.u1)

        self._login(self.u1)

        apipath = f"/api/v1/files/{p1.id}/file.data/"

        # One file of 750kb is under quota of 1mb
        response = self.client.post(
            apipath, {"file": get_random_file(mb=0.75)}, format="multipart"
        )
        self.assertTrue(status.is_success(response.status_code))

        # A second file of 750kb is over quota of 1mb
        response = self.client.post(
            apipath, {"file": get_random_file(mb=0.75)}, format="multipart"
        )
        self.assertEqual(response.status_code, 402)

    def test_api_enforces_storage_limit_when_owner_changes(self):
        plan_10mb = Plan.objects.create(
            code="plan_10mb", storage_mb=10, is_premium=True
        )
        plan_20mb = Plan.objects.create(
            code="plan_20mb", storage_mb=20, is_premium=True
        )

        u10mb = Person.objects.create(username="u10mb")
        u10mb_subscription = u10mb.useraccount.current_subscription
        u10mb_subscription.plan = plan_10mb
        u10mb_subscription.save()

        u20mb = Person.objects.create(username="u20mb")
        u20mb_subscription = u20mb.useraccount.current_subscription
        u20mb_subscription.plan = plan_20mb
        u20mb_subscription.save()

        p1 = Project.objects.create(name="p1", owner=u20mb)

        self._login(u20mb)

        self.assertStorage(
            active_storage_total_mb=10,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=10,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=10,
            user=u10mb,
        )
        self.assertStorage(
            active_storage_total_mb=20,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=20,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=20,
            user=u20mb,
        )

        # User 2 uploads a 15mb file
        apipath = f"/api/v1/files/{p1.id}/file.data/"
        response = self.client.post(
            apipath, {"file": get_random_file(mb=15)}, format="multipart"
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertFalse(Project.objects.filter(owner=u10mb).exists())
        self.assertTrue(Project.objects.filter(owner=u20mb).exists())

        self.assertStorage(
            active_storage_total_mb=20,
            active_storage_package=None,
            active_storage_package_quantity=0,
            active_storage_package_mb=0,
            future_storage_total_mb=20,
            future_storage_package=None,
            future_storage_package_quantity=0,
            future_storage_package_mb=0,
            future_storage_package_changed_mb=0,
            storage_used_mb=15,
            storage_free_mb=5,
            user=u20mb,
        )

        # Transfers to user1, but too much for his quota, so we refuse transfer
        apipath = f"/api/v1/projects/{p1.id}/"
        response = self.client.patch(apipath, {"owner": "u10mb"})
        self.assertEqual(response.status_code, 402)
        self.assertFalse(Project.objects.filter(owner=u10mb).exists())
        self.assertTrue(Project.objects.filter(owner=u20mb).exists())

        # User 1 buys a package, transfer now works
        (
            _old_package,
            new_package,
        ) = u10mb.useraccount.current_subscription.set_package_quantity(
            PackageType.get_storage_package_type(), 1
        )

        self.assertStorage(
            active_storage_total_mb=1010,
            active_storage_package=new_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1010,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=0,
            storage_free_mb=1010,
            user=u10mb,
        )

        response = self.client.patch(apipath, {"owner": "u10mb"})
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(Project.objects.filter(owner=u10mb).exists())
        self.assertFalse(Project.objects.filter(owner=u20mb).exists())

        self.assertStorage(
            active_storage_total_mb=1010,
            active_storage_package=new_package,
            active_storage_package_quantity=1,
            active_storage_package_mb=1000,
            future_storage_total_mb=1010,
            future_storage_package=None,
            future_storage_package_quantity=1,
            future_storage_package_mb=1000,
            future_storage_package_changed_mb=0,
            storage_used_mb=15,
            storage_free_mb=995,
            user=u10mb,
        )
