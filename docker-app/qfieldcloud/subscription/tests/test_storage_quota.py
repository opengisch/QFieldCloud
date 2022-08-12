import logging
from datetime import date, timedelta

from django_currentuser.middleware import _set_current_user
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import utils
from qfieldcloud.core.models import Project, User
from qfieldcloud.core.tests.utils import get_random_file, setup_subscription_plans
from qfieldcloud.core.utils import list_versions
from qfieldcloud.core.utils2.storage import delete_file_version
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from ..models import ExtraPackage, ExtraPackageTypeStorage, Plan

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def setUp(self):
        setup_subscription_plans()

    def test_storage_quota_calculation(self):
        """This tests quotas"""

        u1 = User.objects.create(username="u1")
        p1 = Project.objects.create(name="p1", owner=u1)

        # NOTE since we do not login via the API, the django_currentuser module is unable to set
        # the current user from the request object. Therefore the user set from another test
        # remains in the internal django_currentuser cache and causes the test to fail. So we have
        # to manually reset the current user to None.
        _set_current_user(None)

        default = Plan.get_or_create_default()

        # Initially, we have the default account type storage
        self.assertEqual(u1.useraccount.storage_quota_left_mb, default.storage_mb)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, default.storage_mb)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Changing account type changes the quota
        plan_1mb = Plan.objects.create(code="plan_1mb", storage_mb=1)
        u1.useraccount.plan = plan_1mb
        u1.useraccount.save()
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 1)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 1)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Adding an extra package increases the quota
        extra_2mb = ExtraPackageTypeStorage.objects.create(
            code="extra_2mb", megabytes=2
        )
        ExtraPackage.objects.create(
            account=u1.useraccount,
            type=extra_2mb,
            quantity=1,
            start_date=date.today() - timedelta(days=3),
            end_date=date.today() + timedelta(days=3),
        )
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Adding an obsolete package does not count
        ExtraPackage.objects.create(
            account=u1.useraccount,
            type=extra_2mb,
            quantity=1,
            start_date=date.today() - timedelta(days=3),
            end_date=date.today() - timedelta(days=2),
        )
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Adding a future package does not count
        ExtraPackage.objects.create(
            account=u1.useraccount,
            type=extra_2mb,
            quantity=1,
            start_date=date.today() + timedelta(days=2),
            end_date=date.today() + timedelta(days=3),
        )
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Adding a timeless package increases the quota
        ExtraPackage.objects.create(
            account=u1.useraccount,
            type=extra_2mb,
            quantity=1,
            start_date=date.today() - timedelta(days=3),
            end_date=None,
        )
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 5)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 0)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 5)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 0)

        # Uploading a file decreases the quota
        storage_path = f"projects/{p1.id}/files/test.data"
        bucket = utils.get_s3_bucket()
        bucket.upload_fileobj(get_random_file(mb=1), storage_path)
        p1.save(recompute_storage=True)
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 4)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 1)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 5)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 20)

        # Uploading a new version decreases the quota
        bucket = utils.get_s3_bucket()
        bucket.upload_fileobj(get_random_file(mb=1), storage_path)
        p1.save(recompute_storage=True)
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 3)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 2)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 5)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 40)

        # Deleting a version increases the quota
        version = list(list_versions(bucket, storage_path))[0]
        delete_file_version(p1, "test.data", version.id)
        p1.save(recompute_storage=True)
        self.assertEqual(u1.useraccount.storage_quota_left_mb, 4)
        self.assertEqual(u1.useraccount.storage_quota_used_mb, 1)
        self.assertEqual(u1.useraccount.storage_quota_total_mb, 5)
        self.assertEqual(u1.useraccount.storage_quota_used_perc, 20)

    def test_api_enforces_storage_limit(self):
        u1 = User.objects.create(username="u1")
        p1 = Project.objects.create(name="p1", owner=u1)
        plan_1mb = Plan.objects.create(code="plan_1mb", storage_mb=1)
        u1.useraccount.plan = plan_1mb
        u1.useraccount.save()

        self._login(u1)

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

    def test_api_enforces_storage_limit_for_reparenting(self):
        plan_1mb = Plan.objects.create(code="plan_1mb", storage_mb=1)
        plan_2mb = Plan.objects.create(code="plan_2mb", storage_mb=2)
        extra_1mb = ExtraPackageTypeStorage.objects.create(
            code="extra_1mb", display_name="extra_1mb", megabytes=1
        )

        u1 = User.objects.create(username="u1")
        u1.useraccount.plan = plan_1mb
        u1.useraccount.save()

        u2 = User.objects.create(username="u2")
        u2.useraccount.plan = plan_2mb
        u2.useraccount.save()

        p1 = Project.objects.create(name="p1", owner=u2)

        self._login(u2)

        # User 2 uploads a 1.5mb file
        apipath = f"/api/v1/files/{p1.id}/file.data/"
        response = self.client.post(
            apipath, {"file": get_random_file(mb=1.5)}, format="multipart"
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertFalse(Project.objects.filter(owner=u1).exists())
        self.assertTrue(Project.objects.filter(owner=u2).exists())

        # Transfers to user1, but too much for his quota, so we refuse transfer
        apipath = f"/api/v1/projects/{p1.id}/"
        response = self.client.patch(apipath, {"owner": "u1"})
        self.assertEqual(response.status_code, 402)
        self.assertFalse(Project.objects.filter(owner=u1).exists())
        self.assertTrue(Project.objects.filter(owner=u2).exists())

        # User 1 buys a package, transfer now works
        ExtraPackage.objects.create(
            account=u1.useraccount,
            type=extra_1mb,
            quantity=1,
            start_date=date.today() - timedelta(days=3),
            end_date=None,
        )
        response = self.client.patch(apipath, {"owner": "u1"})
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(Project.objects.filter(owner=u1).exists())
        self.assertFalse(Project.objects.filter(owner=u2).exists())
