from pathlib import Path
from time import sleep

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Job, Project, User
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from ..models import AccountType

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

        # Set external db supported
        AccountType.objects.all().update(is_external_db_supported=True)

        # Upload a projet
        response = self.client.post(
            f"/api/v1/files/{p1.id}/project.qgs/",
            {"file": open(DATA_FOLDER / "project_with_external_db.qgs", "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self._wait(p1, Job.Type.PROCESS_PROJECTFILE)

        # Package it
        response = self.client.post(
            "/api/v1/jobs/",
            {"project_id": p1.id, "type": Job.Type.PACKAGE},
        )
        self.assertTrue(response.status_code, 201)
        self._wait(p1, Job.Type.PACKAGE)

        # Test various endpoints
        for requests_to_check in [
            # TODO: list all endpoints that we wish would fail here
            ["GET", f"/api/v1/packages/{p1.pk}/latest/"],
            ["GET", f"/api/v1/packages/{p1.pk}/latest/files/project.qgs/"],
            # ["GET", f"/api/v1/deltas/{p1.pk}/"],
        ]:
            # If account type has external db permission, endpoint works
            AccountType.objects.all().update(is_external_db_supported=True)
            response = self.client.generic(*requests_to_check)
            self.assertTrue(
                status.is_success(response.status_code),
                f"Unexpected failure: {requests_to_check}",
            )

            # If account type has not external db permission, endpoint fails
            AccountType.objects.all().update(is_external_db_supported=False)
            response = self.client.generic(*requests_to_check)
            self.assertFalse(
                status.is_success(response.status_code),
                f"Unexpected success: {requests_to_check}",
            )

    def test_is_external_db_notsupported(self):
        """This tests is_external_db_supported property of accounts types"""

        u1 = User.objects.create(username="u1")
        p1 = Project.objects.create(name="p1", owner=u1)
        self._login(u1)

        # Set external db not supported
        AccountType.objects.all().update(is_external_db_supported=False)

        # Upload a projet
        response = self.client.post(
            f"/api/v1/files/{p1.id}/project.qgs/",
            {"file": open(DATA_FOLDER / "project_with_external_db.qgs", "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self._wait(p1, Job.Type.PROCESS_PROJECTFILE)

        # Package it (this should fail)
        response = self.client.post(
            "/api/v1/jobs/",
            {"project_id": p1.id, "type": Job.Type.PACKAGE},
        )
        self.assertTrue(response.status_code, 201)
        self._wait(p1, Job.Type.PACKAGE, Job.Status.FAILED)
