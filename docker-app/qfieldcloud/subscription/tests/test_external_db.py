import io
from pathlib import Path
from time import sleep

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Delta, Job, Project, User
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from ..models import AccountType

DATA_FOLDER = Path(__file__).parent / "data"


class QfcTestCase(APITransactionTestCase):

    DELTA_CONTENT = """
    {
        "deltas": [
            {
                "uuid": "9311eb96-bff8-4d5b-ab36-c314a007cfcd",
                "clientId": "cd517e24-a520-4021-8850-e5af70e3a612",
                "exportId": "f70c7286-fcec-4dbe-85b5-63d4735dac47",
                "localPk": "1",
                "sourcePk": "1",
                "localLayerId": "points_897d5ed7_b810_4624_abe3_9f7c0a93d6a1",
                "sourceLayerId": "points_897d5ed7_b810_4624_abe3_9f7c0a93d6a1",
                "method": "patch",
                "new": {
                    "attributes": {
                        "int": 666
                    }
                },
                "old": {
                    "attributes": {
                        "int": 1
                    }
                }
            }
        ],
        "files": [],
        "id": "6f109cd3-f44c-41db-b134-5f38468b9fda",
        "project": "00000000-0000-0000-0000-000000000000",
        "version": "1.0"
    }
    """

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
                    print(job.feedback)
                    raise Exception("Unexpected result failed !")
            # print(".", end="")
            sleep(1)
        else:
            raise Exception("Processing did no finish, did the worker hang ?")

    def test_is_external_db_supported(self):
        """This tests is_external_db_supported property of accounts types"""

        u1 = User.objects.create(username="u1")
        p1 = Project.objects.create(name="p1", owner=u1)
        self._login(u1)

        # Upload a projet
        response = self.client.post(
            f"/api/v1/files/{p1.id}/project.qgs/",
            {"file": open(DATA_FOLDER / "project_with_external_db.qgs", "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self._wait(p1, Job.Type.PROCESS_PROJECTFILE)

        # When external db supported, we can apply deltas
        AccountType.objects.all().update(is_external_db_supported=True)
        response = self.client.post(
            f"/api/v1/deltas/{p1.id}/",
            {
                "file": io.StringIO(
                    self.DELTA_CONTENT.replace(
                        "00000000-0000-0000-0000-000000000000", str(p1.id)
                    )
                )
            },
            format="multipart",
        )
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
        AccountType.objects.all().update(is_external_db_supported=False)
        response = self.client.post(
            f"/api/v1/deltas/{p1.id}/",
            {
                "file": io.StringIO(
                    self.DELTA_CONTENT.replace(
                        "00000000-0000-0000-0000-000000000000", str(p1.id)
                    )
                )
            },
            format="multipart",
        )
        self.assertEqual(
            Delta.objects.filter(project=p1).latest("created_at").last_status,
            Delta.Status.UNPERMITTED,
        )
