import io
import logging

from django.http import FileResponse
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    PackageJob,
    Person,
    Project,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.core.utils2.jobs import repackage
from qfieldcloud.filestorage.models import File

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
            file_storage="default",
            attachments_file_storage="webdav",
        )

    def test_upload_attachment_succeeds(self):
        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)

        file = self.p1.get_file("DCIM/file.name")

        self.assertEqual(file.file_storage, "webdav")

    def test_upload_then_download_attachment_succeeds(self):
        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        response = self._download_file(self.u1, self.p1, "DCIM/file.name")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response, FileResponse)

    def test_upload_then_delete_attachment_succeeds(self):
        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        response = self._delete_file(self.u1, self.p1, "DCIM/file.name")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_upload_attachment_then_change_storage_succeeds(self):
        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file1.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 1)

        file1 = self.p1.get_file("DCIM/file1.name")

        self.assertEqual(file1.file_storage, "webdav")

        # change project's storage to default
        self.p1.attachments_file_storage = "default"
        self.p1.save(update_fields=["attachments_file_storage"])

        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file2.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 2)

        file2 = self.p1.get_file("DCIM/file2.name")

        self.assertEqual(file2.file_storage, "default")

        # change project's storage to webdav again
        self.p1.attachments_file_storage = "webdav"
        self.p1.save(update_fields=["attachments_file_storage"])

        response = self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file3.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.p1.project_files.count(), 3)

        file3 = self.p1.get_file("DCIM/file3.name")

        self.assertEqual(file3.file_storage, "webdav")

    def test_attachments_packages_on_default_storage_succeeds(self):
        # upload data & QGIS project files to the project.
        self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self._upload_file(
            self.u1,
            self.p1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        # upload an attachment
        self._upload_file(
            self.u1,
            self.p1,
            "DCIM/file.name",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self.p1.refresh_from_db()
        package_job = repackage(self.p1, self.u1)

        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        # ensure the attachment is stored on webdav storage.
        file_attachment = self.p1.get_file("DCIM/file.name")

        self.assertEqual(file_attachment.file_storage, "webdav")

        # ensure the package files are stored on default storage.
        package_jobs_qs = PackageJob.objects.filter(project=self.p1)

        for package_job in package_jobs_qs:
            package_files_qs = File.objects.filter(
                project=self.p1, package_job=package_job
            )

            for package_file in package_files_qs:
                self.assertEquals(
                    package_file.file_storage,
                    "default",
                )
