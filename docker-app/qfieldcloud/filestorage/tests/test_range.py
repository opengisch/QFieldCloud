import logging
from io import StringIO

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Person,
    Project,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]
        self.p1 = Project.objects.create(
            owner=self.u1,
            name="p1",
        )

    def test_upload_file_then_download_range_succeeds(self):
        # first upload of the file
        response = self._upload_file(
            self.u1, self.p1, "file.name", StringIO("abcdefghijkl")
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        # download parts of the file, with specific ranges
        r1 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=0-2"}
        )

        self.assertEquals(r1.status_code, status.HTTP_206_PARTIAL_CONTENT)
        self.assertEquals(r1.content, b"abc")

        r2 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=5-8"}
        )

        self.assertEquals(r2.status_code, status.HTTP_206_PARTIAL_CONTENT)
        self.assertEquals(r2.content, b"fghi")

        r3 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=7-"}
        )

        self.assertEquals(r3.status_code, status.HTTP_206_PARTIAL_CONTENT)
        self.assertEquals(r3.content, b"hijkl")

        r4 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=0-"}
        )

        self.assertEquals(r4.status_code, status.HTTP_206_PARTIAL_CONTENT)
        self.assertEquals(r4.content, b"abcdefghijkl")

    def test_upload_file_then_download_wrong_range_fails(self):
        # first upload of the file
        self._upload_file(self.u1, self.p1, "file.name", StringIO("abcdefghijkl"))

        r1 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=abc-"}
        )

        self.assertEquals(r1.status_code, status.HTTP_400_BAD_REQUEST)

        r2 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=-def"}
        )

        self.assertEquals(r2.status_code, status.HTTP_400_BAD_REQUEST)

        r3 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=-1-"}
        )

        self.assertEquals(r3.status_code, status.HTTP_400_BAD_REQUEST)

        r4 = self._download_file(
            self.u1, self.p1, "file.name", headers={"Range": "bytes=1-55"}
        )

        self.assertEquals(r4.status_code, status.HTTP_400_BAD_REQUEST)
