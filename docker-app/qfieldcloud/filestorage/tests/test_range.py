import logging
from io import StringIO

from django.test import override_settings
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
from qfieldcloud.filestorage.utils import parse_range

logging.disable(logging.CRITICAL)


@override_settings(QFIELDCLOUD_MINIMUM_RANGE_HEADER_LENGTH=0)
class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]
        self.project_default_storage = Project.objects.create(
            owner=self.u1,
            name="project_default_storage",
            file_storage="default",
        )
        self.project_webdav_storage = Project.objects.create(
            owner=self.u1,
            name="project_webdav_storage",
            file_storage="webdav",
        )

    def test_parsing_range_function_succeeds(self):
        self.assertEquals(parse_range("bytes=4-8", 10), (4, 8))

        start_byte, end_byte = parse_range("bytes=2-", 10)

        self.assertEquals(start_byte, 2)
        self.assertIsNone(end_byte)

    def test_parsing_wrong_invalid_range_function_succeeds(self):
        file_size = 1000000

        # not starting with 'bytes'
        self.assertIsNone(parse_range("byte=4-8", file_size))

        # start byte can not be negative
        self.assertIsNone(parse_range("bytes=-1-15", file_size))

        # start and end bytes can not be negative
        self.assertIsNone(parse_range("bytes=-10--15", file_size))

        # start position cannot be greater than the end position
        self.assertIsNone(parse_range("bytes=9-1", file_size))

        # suffix ranges are not supported (yet), see https://www.rfc-editor.org/rfc/rfc9110.html#rule.suffix-range
        self.assertIsNone(parse_range("bytes=-5", file_size))

        # bytes should be numbers
        self.assertIsNone(parse_range("bytes=one-two", file_size))
        # whitespaces are not accepted
        self.assertIsNone(parse_range("bytes= 1-9", file_size))
        self.assertIsNone(parse_range("bytes=1 -9", file_size))
        self.assertIsNone(parse_range("bytes=1- 9", file_size))
        self.assertIsNone(parse_range("bytes=1-9 ", file_size))
        self.assertIsNone(parse_range("bytes=1- ", file_size))
        self.assertIsNone(parse_range(" bytes=1-9", file_size))
        # typos in bytes
        self.assertIsNone(parse_range("bites=0-9", file_size))
        self.assertIsNone(parse_range("starting bytes=0-9", file_size))
        self.assertIsNone(parse_range("bytes=0-9 closing bytes", file_size))
        # empty range
        self.assertIsNone(parse_range("bytes=0-0", file_size))
        self.assertIsNone(parse_range("bytes=1-1", file_size))
        # multiple ranges are not supported (yet), see https://www.rfc-editor.org/rfc/rfc9110.html#section-14.1.2-9.4.1
        self.assertIsNone(parse_range("bytes=1-5, 10-15", file_size))
        self.assertIsNone(parse_range("bytes=1-5,10-15", file_size))

    def test_upload_file_then_download_range_succeeds(self):
        for project in [self.project_default_storage, self.project_webdav_storage]:
            # first upload of the file
            response = self._upload_file(
                self.u1, project, "file.name", StringIO("abcdefghijkl")
            )

            with self.subTest(case=project):
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(project.project_files.count(), 1)
                self.assertEqual(project.get_file("file.name").versions.count(), 1)

                # download parts of the file, with specific ranges
                r1 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=0-2"}
                )

                self.assertEquals(r1.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEquals(r1.content, b"abc")

                r2 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=5-8"}
                )

                self.assertEquals(r2.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEquals(r2.content, b"fghi")

                r3 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=7-"}
                )

                self.assertEquals(r3.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEquals(r3.content, b"hijkl")

                r4 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=0-"}
                )

                self.assertEquals(r4.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEquals(r4.content, b"abcdefghijkl")

    @override_settings(QFIELDCLOUD_MINIMUM_RANGE_HEADER_LENGTH=3)
    def test_minimum_range_header_length(self):
        for project in [self.project_default_storage, self.project_webdav_storage]:
            # first upload of the file
            response = self._upload_file(
                self.u1, project, "file.name", StringIO("abcdefghijkl")
            )

            with self.subTest(case=project):
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(project.project_files.count(), 1)
                self.assertEqual(project.get_file("file.name").versions.count(), 1)

                # download parts of the file, with specific ranges
                r1 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=0-2"}
                )

                self.assertEquals(r1.status_code, status.HTTP_206_PARTIAL_CONTENT)
                self.assertEquals(r1.content, b"abc")

                # download parts of the file, with specific ranges
                r1 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=0-1"}
                )

                self.assertEquals(
                    r1.status_code, status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
                )

    def test_upload_file_then_download_wrong_range_fails(self):
        for project in [self.project_default_storage, self.project_webdav_storage]:
            # first upload of the file
            self._upload_file(self.u1, project, "file.name", StringIO("abcdefghijkl"))

            with self.subTest(case=project):
                r1 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=abc-"}
                )

                self.assertEquals(
                    r1.status_code, status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
                )

                r2 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=-def"}
                )

                self.assertEquals(
                    r2.status_code, status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
                )

                r3 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=-1-"}
                )

                self.assertEquals(
                    r3.status_code, status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
                )

                r4 = self._download_file(
                    self.u1, project, "file.name", headers={"Range": "bytes=1-55"}
                )

                self.assertEquals(
                    r4.status_code, status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
                )
