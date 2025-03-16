import io
import json
from pathlib import Path
from time import sleep

import psycopg2
from django.conf import settings
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.geodb_utils import delete_db_and_role
from qfieldcloud.core.models import Delta, Geodb, Job, Person, Project
from qfieldcloud.core.tests.utils import setup_subscription_plans

from ..models import Plan

DATA_FOLDER = Path(__file__).parent / "data"


class QfcTestCase(APITransactionTestCase):
    def _login(self, user):
        token = AuthToken.objects.get_or_create(user=user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def _wait(self, project, job_type, expected_result=Job.Status.FINISHED):
        # print(f"Waiting for {job_type} status {expected_result}", end="")
        for _ in range(30):
            job = (
                Job.objects.filter(project=project, type=job_type)
                .exclude(
                    status__in=[
                        Job.Status.PENDING,
                        Job.Status.QUEUED,
                        Job.Status.STARTED,
                    ]
                )
                .last()
            )
            if job:
                if job.status == expected_result:
                    # print(" done")
                    break
                else:
                    print(f" got unexpected result ! ({job.status})")
                    print("~~~~~~~~~~~~~~~~~~~~~~")
                    print(job.feedback)
                    print("~~~~~~~~~~~~~~~~~~~~~~")
                    raise Exception("Unexpected result failed !")
            # print(".", end="")
            sleep(1)
        else:
            raise Exception("Processing did no finish, did the worker hang ?")

    def _get_delta_file_with_project_id(self, project, delta_filename):
        """Retrieves a delta json file with the project id replaced by the project.id"""
        with open(delta_filename) as f:
            deltafile = json.load(f)
            deltafile["project"] = str(project.id)
            json_str = json.dumps(deltafile)
            return io.StringIO(json_str)

    def setUp(self):
        setup_subscription_plans()

    def test_is_external_db_supported(self):
        """This tests is_external_db_supported property of accounts types"""

        u1 = Person.objects.create(username="u1")
        self._login(u1)

        # Create a project with a writable remote DB

        p1 = Project.objects.create(name="p1", owner=u1)

        delete_db_and_role("test", "usr1")
        Geodb.objects.create(
            dbname="test",
            user=u1,
            username="usr1",
            password="pwd",
            hostname=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
        )
        conn = psycopg2.connect(
            dbname="test",
            user="usr1",
            password="pwd",
            host=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
        )
        conn.cursor().execute("CREATE TABLE point (id integer PRIMARY KEY, name text)")
        conn.commit()

        # Upload the project file and ensure it loaded

        response = self.client.post(
            f"/api/v1/files/{p1.id}/project.qgs/",
            {"file": open(DATA_FOLDER / "project_pgservice.qgs", "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self._wait(p1, Job.Type.PROCESS_PROJECTFILE)

        # Ensure we start without delta

        self.assertEqual(Delta.objects.filter(project=p1).count(), 0)

        # When external db supported, we can apply deltas

        Plan.objects.all().update(is_external_db_supported=True)
        response = self.client.post(
            f"/api/v1/deltas/{p1.id}/",
            {
                "file": self._get_delta_file_with_project_id(
                    p1, DATA_FOLDER / "project_pgservice_delta_1.json"
                )
            },
            format="multipart",
        )
        self.assertEqual(Delta.objects.filter(project=p1).count(), 1)
        self.assertEqual(
            Delta.objects.filter(project=p1).latest("created_at").last_status,
            Delta.Status.PENDING,
        )
        self._wait(p1, Job.Type.DELTA_APPLY)
        self.assertEqual(
            Delta.objects.filter(project=p1).latest("created_at").last_status,
            Delta.Status.APPLIED,
        )

        # When external db is NOT supported, we can NOT apply deltas

        Plan.objects.all().update(is_external_db_supported=False)
        jobs_count_before = p1.jobs.count()
        response = self.client.post(
            f"/api/v1/deltas/{p1.id}/",
            {
                "file": self._get_delta_file_with_project_id(
                    p1, DATA_FOLDER / "project_pgservice_delta_2.json"
                )
            },
            format="multipart",
        )

        self.assertEqual(Delta.objects.filter(project=p1).count(), 2)

        print("-------------------")

        for delta in Delta.objects.filter(project=p1):
            print(delta)

        self.assertEqual(
            Delta.objects.filter(project=p1).latest("created_at").last_status,
            Delta.Status.PENDING,
        )
        # No Apply Job is created
        self.assertEqual(p1.jobs.count(), jobs_count_before)

        # TODO When external db is supported again apply pending deltas
