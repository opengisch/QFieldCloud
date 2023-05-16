import logging
import os
import pdb
from time import sleep

import psycopg2
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.geodb_utils import delete_db_and_role
from qfieldcloud.core.models import ApplyJob, Geodb, Job, PackageJob, Person, Project
from qfieldcloud.subscription.exceptions import SubscriptionException
from qfieldcloud.subscription.models import SubscriptionStatus
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from .utils import setup_subscription_plans, testdata_path

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
            # user_agent="qfield|dev", # FIXME TODO remove?
        )[0]

        self.token_worker = AuthToken.objects.get_or_create(
            user=self.project.owner,
            client_type=AuthToken.ClientType.WORKER,
        )[0]

        delete_db_and_role("test", self.user.username)

        self.geodb = Geodb.objects.create(
            user=self.user,
            dbname="test",
            hostname="geodb",
            port=5432,
        )

        self.conn = psycopg2.connect(
            dbname="test",
            user=os.environ.get("GEODB_USER"),
            password=os.environ.get("GEODB_PASSWORD"),
            host="geodb",
            port=5432,
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

    def test_push_file_to_qfield_always_allowed(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token_qfield.key)

        # FIXME TODO 'worker'
        self.assertEqual(self.token_qfield.client_type, AuthToken.ClientType.QFIELD)

        # Check 'project owner' and 'client' user are same to ensure all scenarios
        self.assertEqual(self.project.owner.id, self.token_qfield.user.id)
        account = self.user.useraccount
        subscription = account.current_subscription
        subscription.status = SubscriptionStatus.INACTIVE_DRAFT
        subscription.save()

        self.assertFalse(account.current_subscription.is_active)

        plan = subscription.plan
        plan.storage_mb = 0
        plan.save()
        self.assertEqual(account.storage_free_bytes, 0)

        self.add_qfis_project_file()
        # Create a project that uses all the storage
        # more_bytes_than_plan = (plan.storage_mb * 1000 * 1000) + 1
        # Project.objects.create(
        #     name="p1",
        #     owner=self.user,
        #     file_storage_bytes=more_bytes_than_plan,
        # )

        # A cross check that no delta apply or package jobs can be created on the project
        with self.assertRaises(SubscriptionException):
            PackageJob.objects.create(
                type=Job.Type.PACKAGE, project=self.project, created_by=self.user
            )
        with self.assertRaises(SubscriptionException):
            ApplyJob.objects.create(
                type=Job.Type.DELTA_APPLY, project=self.project, created_by=self.user
            )

        response = self.client.post(
            "/api/v1/qfield-files/export/{}/".format(self.project.id)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def add_qfis_project_file(self):
        file = testdata_path("delta/project2.qgs")
        response = self.client.post(
            "/api/v1/files/{}/project.qgs/".format(self.project.id),
            {"file": open(file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        sleep(5)
        self.project.refresh_from_db()
        self.assertTrue(self.project.has_online_vector_data)
