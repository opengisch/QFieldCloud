import logging
from io import StringIO

from django.http import FileResponse
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
            file_storage="webdav",
        )

    def test_upload_file_succeeds(self):
        # 1) first upload of the file
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 1)

        # 2) adding a second version
        response = self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello2!"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)
        self.assertEqual(self.p1.get_file("file.name").versions.count(), 2)

    def test_upload_then_download_file_succeeds(self):
        # 1) first upload of the file
        self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        # 2) download file
        response = self._download_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(b"".join(response.streaming_content), b"Hello!")

    def test_upload_then_delete_file_succeeds(self):
        # 1) first upload of the file
        self._upload_file(self.u1, self.p1, "file.name", StringIO("Hello!"))

        # 2) delete file
        response = self._delete_file(self.u1, self.p1, "file.name")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
