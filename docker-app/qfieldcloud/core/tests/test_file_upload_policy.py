import logging

import psycopg2
from django.conf import settings
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.geodb_utils import delete_db_and_role
from qfieldcloud.core.models import ApplyJob, Geodb, Job, PackageJob, Person, Project
from qfieldcloud.subscription.exceptions import SubscriptionException
from qfieldcloud.subscription.models import SubscriptionStatus

from .utils import setup_subscription_plans, testdata_path, wait_for_project_ok_status

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    """
    The current policy is that a user can always push/upload a file to QFieldCloud
    from the field, i.e. from Qfield. Also we already running jobs can always upload
    files. Therefore we check for the client type in the post request.
    """

    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user = Person.objects.create_user(username="user", password="abc123")

        # Create a project
        self.project = Project.objects.create(
            name="project1", is_public=False, owner=self.user
        )

        # We ensure the project owner and the post request sender are the same
        # because (currently) we want the request to succeed no matter who sends it.
        self.token_qfield = AuthToken.objects.get_or_create(
            user=self.project.owner,
            client_type=AuthToken.ClientType.QFIELD,
        )[0]

        self.token_worker = AuthToken.objects.get_or_create(
            user=self.project.owner,
            client_type=AuthToken.ClientType.WORKER,
        )[0]

        self.token_qfieldsync = AuthToken.objects.get_or_create(
            user=self.project.owner,
            client_type=AuthToken.ClientType.QFIELDSYNC,
        )[0]

        self.assertEqual(self.project.owner.id, self.token_qfield.user.id)

        account = self.user.useraccount
        subscription = account.current_subscription
        subscription.status = SubscriptionStatus.INACTIVE_DRAFT
        subscription.save()
        # Check user has inactive subscription
        self.assertFalse(account.current_subscription.is_active)
        # Check user cannot have online vector data
        self.assertFalse(subscription.plan.is_external_db_supported)

        plan = subscription.plan
        plan.storage_mb = 0
        plan.save()

        delete_db_and_role("test", self.user.username)

        self.geodb = Geodb.objects.create(
            user=self.user,
            dbname="test",
            hostname=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
        )

        self.conn = psycopg2.connect(
            dbname="test",
            user=settings.GEODB_USER,
            password=settings.GEODB_PASSWORD,
            host=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
        )

        cur = self.conn.cursor()

        cur.execute(
            """
            CREATE TABLE point (
                id          integer,
                geometry   geometry(point, 2056)
            );
            """
        )

        self.conn.commit()

        cur.execute(
            """
            INSERT INTO point(id, geometry)
            VALUES(1, ST_GeomFromText('POINT(2725505 1121435)', 2056));
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_always_accept_file_from_qfield(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token_qfield.key)

        self.assertEqual(self.token_qfield.client_type, AuthToken.ClientType.QFIELD)

        response = self.add_qgis_project_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)

        self.project.refresh_from_db()
        self.assertTrue(self.project.has_online_vector_data)

        # Check user has no storage left
        self.assertTrue(self.user.useraccount.storage_free_bytes < 0)

        response = self.add_text_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)

        response = self.change_qgis_project_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)

        # Cannot not sync or download data because we prevent creating a Package Job
        response = self.trigger_package_job()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "inactive_subscription")
        self.cross_check_prevent_package_and_apply_job()

    def test_always_accept_file_from_worker(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token_worker.key)

        response = self.add_qgis_project_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)
        self.assertTrue(self.project.has_online_vector_data)

        # Check user has no storage left
        self.assertTrue(self.user.useraccount.storage_free_bytes < 0)

        response = self.add_text_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)

        response = self.change_qgis_project_file()
        self.assertTrue(status.is_success(response.status_code))
        wait_for_project_ok_status(self.project)

        # Cannot not sync or download data because we prevent creating a Package Job
        response = self.trigger_package_job()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "inactive_subscription")

    def test_upload_file_unpermitted_from_qfieldsync(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token_qfieldsync.key)

        response = self.add_qgis_project_file()
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)

        response = self.add_text_file()
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)

        self.assertEqual(self.project.jobs.count(), 0)

        # Cannot not sync or download data because we prevent creating a Package Job
        response = self.trigger_package_job()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "no_qgis_project")

    def add_qgis_project_file(self):
        file = testdata_path("delta/project2.qgs")
        return self.client.post(
            f"/api/v1/files/{self.project.id}/project.qgs/",
            {"file": open(file, "rb")},
            format="multipart",
        )

    def change_qgis_project_file(self):
        file = testdata_path("delta/project.qgs")
        return self.client.post(
            f"/api/v1/files/{self.project.id}/project.qgs/",
            {"file": open(file, "rb")},
            format="multipart",
        )

    def add_text_file(self):
        file = testdata_path("file.txt")
        return self.client.post(
            f"/api/v1/files/{self.project.id}/file.txt/",
            {"file": open(file, "rb")},
            format="multipart",
        )

    def trigger_package_job(self):
        return self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": self.project.id,
                "type": Job.Type.PACKAGE.value,
            },
        )

    def cross_check_prevent_package_and_apply_job(self):
        # A cross check that no delta apply or package jobs can be created on the project
        with self.assertRaises(SubscriptionException):
            PackageJob.objects.create(
                type=Job.Type.PACKAGE, project=self.project, created_by=self.user
            )

        with self.assertRaises(SubscriptionException):
            ApplyJob.objects.create(
                type=Job.Type.DELTA_APPLY, project=self.project, created_by=self.user
            )
