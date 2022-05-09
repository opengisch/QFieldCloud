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

    def test_is_external_db_supported(self):
        """This tests is_external_db_supported property of accounts types"""

        u1 = User.objects.create(username="u1")
        p1 = Project.objects.create(name="p1", owner=u1)
        self._login(u1)

        # Upload a projet and wait until it's processed
        response = self.client.post(
            f"/api/v1/files/{p1.id}/project.qgs/",
            {"file": open(DATA_FOLDER / "project_with_external_db.qgs", "rb").read()},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        raise Exception(Job.objects.all())

        for _ in range(30):
            if Project.objects.get(pk=p1.id).status == Project.Status.OK:
                break
            sleep(1)
        else:
            raise Exception("Project was not imported, did the worker fail ?")

        # Test some endpoints
        for endpoint_to_check in [
            f"packages/{p1.pk}/latest/",
            f"packages/{p1.pk}/latest/files/project.qgs/",
        ]:
            # If account type has external db permission, all endpoint works
            AccountType.objects.all().update(is_external_db_supported=True)
            response = self.client.get(endpoint_to_check)
            self.assertTrue(status.is_success(response.status_code))

            # If account type has not external db permission, endpoint fails
            AccountType.objects.all().update(is_external_db_supported=True)
            response = self.client.get(endpoint_to_check)
            self.assertFalse(status.is_success(response.status_code))
