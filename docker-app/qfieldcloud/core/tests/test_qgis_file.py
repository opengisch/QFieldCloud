import io
import logging
import tempfile
import time
from pathlib import PurePath

from django.http import FileResponse
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Job, Person, ProcessProjectfileJob, Project

from .utils import (
    get_filename,
    set_subscription,
    setup_subscription_plans,
    testdata_path,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.user1.save()

        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.user2.save()

        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )
        self.project1.save()

    def get_file_contents(self, project, filename, version=None):
        qs = ""
        if version:
            qs = f"?version={version}"

        response = self.client.get(f"/api/v1/files/{project.id}/{filename}/{qs}")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), PurePath(filename).name)

        if isinstance(response, FileResponse):
            return b"".join(response.streaming_content)
        else:
            return response.content

    def test_try_to_get_nonexistent_project(self):
        empty_string = ""
        nonexistent_id = "007"
        with self.subTest(
            "Ensure that '/api/v1/files' handles missing resources correctly."
        ):
            one = self.client.get(f"/api/v1/files/{empty_string}")
            two = self.client.get(f"/api/v1/files/{nonexistent_id}")
            assert all(r.status_code == 404 for r in (one, two))

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

    def test_push_multiple_files(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        # Upload multiple files
        file1 = io.FileIO(testdata_path("DCIM/1.jpg"), "rb")
        file2 = io.FileIO(testdata_path("DCIM/2.jpg"), "rb")
        file3 = io.FileIO(testdata_path("file.txt"), "rb")
        data = {"file": [file1, file2, file3]}

        # Assert that it didn't work
        with self.subTest():
            response = self.client.post(
                f"/api/v1/files/{self.project1.id}/file.txt/",
                data=data,
                format="multipart",
            )
            self.assertEqual(response.json()["code"], "multiple_contents")
            self.assertEqual(
                Project.objects.get(pk=self.project1.pk).project_files_count, 0
            )
            self.assertEqual(
                Project.objects.get(pk=self.project1.pk).the_qgis_file_name, None
            )

        with self.subTest():
            response = self.client.post(
                f"/api/v1/files/{self.project1.id}/file.txt/",
                data={"file": []},
                format="multipart",
            )
            self.assertEqual(response.json()["code"], "empty_content")
            self.assertEqual(
                Project.objects.get(pk=self.project1.pk).project_files_count, 0
            )
            self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

    def test_push_download_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        self.assertEqual(
            self.get_file_contents(self.project1, "file.txt"),
            open(testdata_path("file.txt"), "rb").read(),
        )

    def test_push_download_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/foo/bar/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        # Pull the file
        response = self.client.get(
            f"/api/v1/files/{self.project1.id}/foo/bar/file.txt/",
            stream=True,
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "file.txt")

        self.assertEqual(
            self.get_file_contents(self.project1, "foo/bar/file.txt"),
            open(testdata_path("file.txt"), "rb").read(),
        )

    def test_upload_and_list_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/aaa/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        file_path = testdata_path("file2.txt")
        # Push a second file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file2.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 2
        )

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))

        payload = response.json()
        payload = sorted(payload, key=lambda k: k["name"])

        self.assertEqual(payload[0]["name"], "aaa/file.txt")
        self.assertEqual(payload[0]["size"], 13)
        self.assertEqual(payload[1]["name"], "file2.txt")
        self.assertEqual(payload[1]["size"], 13)
        # check sha256
        self.assertEqual(
            payload[0]["sha256"],
            "8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d",
        )
        self.assertEqual(
            payload[1]["sha256"],
            "fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9",
        )
        # check md5sum
        self.assertEqual(payload[0]["md5sum"], "9af2f8218b150c351ad802c6f3d66abe")
        self.assertEqual(payload[1]["md5sum"], "3bf4cfdddae3137d565094635a8ebcc9")

    def test_upload_and_list_file_checksum(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        # List files without `skip_metadata` param
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()

        self.assertEqual(json[0]["name"], "file.txt")
        self.assertEqual(json[0]["size"], 13)
        self.assertIn("sha256", json[0])
        self.assertIn("md5sum", json[0])
        self.assertEqual(
            json[0]["sha256"],
            "8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d",
        )
        self.assertEqual(
            json[0]["md5sum"],
            "9af2f8218b150c351ad802c6f3d66abe",
        )

        # List files with `skip_metadata=0` param
        response = self.client.get(f"/api/v1/files/{self.project1.id}/?skip_metadata=0")
        self.assertEqual(json[0]["name"], "file.txt")
        self.assertEqual(json[0]["size"], 13)
        self.assertIn("sha256", json[0])
        self.assertIn("md5sum", json[0])
        self.assertEqual(
            json[0]["sha256"],
            "8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d",
        )
        self.assertEqual(
            json[0]["md5sum"],
            "9af2f8218b150c351ad802c6f3d66abe",
        )

        # List files with `skip_metadata=1` param
        response = self.client.get(f"/api/v1/files/{self.project1.id}/?skip_metadata=1")
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()

        self.assertEqual(json[0]["name"], "file.txt")
        self.assertEqual(json[0]["size"], 13)

        # The `sha256` key is optional only for the legacy storage, there is no performance penalty for the non-legacy storage if we send it back,
        # therefore `skip_metadata` is ignored in non-legacy storage
        # TODO Delete with QF-4963 Drop support for legacy storage
        if self.project1.uses_legacy_storage:
            self.assertNotIn("sha256", json[0])

        self.assertIn("md5sum", json[0])
        self.assertEqual(
            json[0]["md5sum"],
            "9af2f8218b150c351ad802c6f3d66abe",
        )

    def test_upload_and_list_file_with_space_in_name(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        project_file = "aaa bbb/project qgis 1.2.qgs"
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/{project_file}/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).the_qgis_file_name, project_file
        )

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()

        self.assertEqual(json[0]["name"], "aaa bbb/project qgis 1.2.qgs")

    def test_upload_and_list_file_versions(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.get(pk=self.project1.pk)

        self.assertEqual(project.project_files_count, 0)
        self.assertEqual(project.file_storage_bytes, 0)
        self.assertFalse(project.has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/aaa/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 13)
        self.assertFalse(project.has_the_qgis_file)

        # Wait 2 seconds to be sure the file timestamps are different
        time.sleep(2)

        file_path = testdata_path("file2.txt")
        # Push another file with the same name (i.e. push another
        # version)
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/aaa/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 26)
        self.assertFalse(project.has_the_qgis_file)

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))

        payload = response.json()
        versions = sorted(payload[0]["versions"], key=lambda k: k["last_modified"])

        self.assertEqual(len(versions), 2)
        self.assertNotEqual(versions[0]["last_modified"], versions[1]["last_modified"])

        self.assertEqual(
            versions[0]["sha256"],
            "8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d",
        )
        self.assertEqual(
            versions[1]["sha256"],
            "fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9",
        )
        self.assertEqual(versions[0]["md5sum"], "9af2f8218b150c351ad802c6f3d66abe")
        self.assertEqual(versions[1]["md5sum"], "3bf4cfdddae3137d565094635a8ebcc9")
        self.assertEqual(payload[0]["sha256"], versions[1]["sha256"])
        self.assertEqual(payload[0]["md5sum"], versions[1]["md5sum"])

        self.assertEqual(versions[0]["size"], 13)
        self.assertEqual(versions[1]["size"], 13)

    def test_push_download_specific_version_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        # Wait 2 seconds to be sure the file timestamps are different
        time.sleep(2)

        file_path = testdata_path("file2.txt")
        # Push another file with the same name (i.e. push another
        # version)
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )

        self.assertNotEqual(
            self.get_file_contents(self.project1, "file.txt"),
            open(testdata_path("file.txt"), "rb").read(),
        )

        self.assertEqual(
            self.get_file_contents(self.project1, "file.txt"),
            open(testdata_path("file2.txt"), "rb").read(),
        )

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))

        versions = sorted(
            response.json()[0]["versions"], key=lambda k: k["last_modified"]
        )

        # Pull the oldest version
        self.assertEqual(
            self.get_file_contents(
                self.project1, "file.txt", versions[0]["version_id"]
            ),
            open(testdata_path("file.txt"), "rb").read(),
        )

        # Pull the newest version
        self.assertEqual(
            self.get_file_contents(
                self.project1, "file.txt", versions[1]["version_id"]
            ),
            open(testdata_path("file2.txt"), "rb").read(),
        )

    def test_push_delete_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        project = Project.objects.get(pk=self.project1.pk)

        self.assertEqual(project.project_files_count, 0)
        self.assertEqual(project.file_storage_bytes, 0)
        self.assertFalse(project.has_the_qgis_file)

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/aaa/file.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 13)
        self.assertFalse(project.has_the_qgis_file)

        file_path = testdata_path("file2.txt")
        # Push a second file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/file2.txt/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 2)
        self.assertEqual(project.file_storage_bytes, 26)
        self.assertFalse(project.has_the_qgis_file)

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 2)

        # Delete a file
        response = self.client.delete(f"/api/v1/files/{self.project1.id}/aaa/file.txt/")
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 13)
        self.assertFalse(project.has_the_qgis_file)

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)

    def test_one_qgis_project_per_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        qgis_project_file = "foo/bar/file.qgs"
        # Push a QGIS project file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/{qgis_project_file}/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).the_qgis_file_name,
            qgis_project_file,
        )

        # Push again the same QGIS project file (this is allowed)
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/{qgis_project_file}/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).the_qgis_file_name,
            qgis_project_file,
        )

        failing_qgis_project_file = "foo/bar/file2.qgs"
        # Push another QGIS project file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/{failing_qgis_project_file}/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).the_qgis_file_name,
            qgis_project_file,
        )

        # Push another QGIS project file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/foo/bar/file2.qgz/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 1
        )
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).the_qgis_file_name,
            qgis_project_file,
        )

        response = self.client.delete(
            f"/api/v1/files/{self.project1.id}/{qgis_project_file}/",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

    def test_upload_1mb_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        big_file = tempfile.NamedTemporaryFile()
        with open(big_file.name, "wb") as bf:
            bf.truncate(1000 * 1000 * 1)

        # Push the file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/bigfile.big/",
            data={"file": open(big_file.name, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 1000000)

        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)
        self.assertEqual("bigfile.big", response.json()[0]["name"])
        self.assertEqual(response.json()[0]["size"], 1000000)

    def test_upload_10mb_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        big_file = tempfile.NamedTemporaryFile()
        with open(big_file.name, "wb") as bf:
            bf.truncate(1000 * 1000 * 10)

        # Push the file
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/bigfile.big/",
            data={"file": open(big_file.name, "rb")},
            format="multipart",
        )
        project = Project.objects.get(pk=self.project1.pk)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(project.project_files_count, 1)
        self.assertEqual(project.file_storage_bytes, 10000000)
        # List files
        response = self.client.get(f"/api/v1/files/{self.project1.id}/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)
        self.assertEqual("bigfile.big", response.json()[0]["name"])
        self.assertEqual(response.json()[0]["size"], 10000000)

    def test_purge_old_versions(self):
        """This tests automated purging of old versions when uploading files"""

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        apipath = f"/api/v1/files/{self.project1.id}/file.txt/"

        def count_versions():
            """counts the versions in first file of project1"""
            project = Project.objects.get(pk=self.project1.pk)

            # TODO Delete with QF-4963 Drop support for legacy storage
            if project.uses_legacy_storage:
                return len(project.legacy_get_file("file.txt").versions)
            else:
                return project.get_file("file.txt").versions.count()

        def read_version(n):
            """returns the content of version in first file of project1"""
            project = Project.objects.get(pk=self.project1.pk)

            # TODO Delete with QF-4963 Drop support for legacy storage
            if project.uses_legacy_storage:
                file = (
                    project.legacy_get_file("file.txt").versions[n]._data.get()["Body"]
                )
            else:
                file = (
                    project.get_file("file.txt")
                    .versions.all()
                    .order_by("uploaded_at")[n]
                    .content
                )

            return file.read().decode()

        # As PRO account, 10 version should be kept out of 20
        set_subscription(self.user1, "keep_10", storage_keep_versions=10)

        for i in range(20):
            test_file = io.StringIO(f"v{i}")
            self.client.post(apipath, {"file": test_file}, format="multipart")

        self.assertEqual(count_versions(), 10)
        self.assertEqual(read_version(0), "v10")
        self.assertEqual(read_version(9), "v19")

        # As COMMUNITY account, 3 version should be kept
        set_subscription(self.user1, "keep_3", storage_keep_versions=3)

        # But first we check that uploading to another project doesn't affect a projct
        otherproj = Project.objects.create(name="other", owner=self.user1)
        otherpath = f"/api/v1/files/{otherproj.id}/file.txt/"
        self.client.post(otherpath, {"file": io.StringIO("v1")}, format="multipart")
        self.assertEqual(count_versions(), 10)
        self.assertEqual(read_version(0), "v10")
        self.assertEqual(read_version(9), "v19")

        # As COMMUNITY account, 3 version should be kept out of 20 new ones
        for i in range(20, 40):
            test_file = io.StringIO(f"v{i}")
            self.client.post(apipath, {"file": test_file}, format="multipart")

        self.assertEqual(count_versions(), 3)
        self.assertEqual(read_version(0), "v37")
        self.assertEqual(read_version(2), "v39")

    def test_multiple_file_uploads_one_process_job(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_files_count, 0
        )
        self.assertFalse(Project.objects.get(pk=self.project1.pk).has_the_qgis_file)

        file_path = testdata_path("file.txt")
        qgis_project_file = "foo/bar/file.qgs"

        for i in range(10):
            # Push a QGIS project file
            response = self.client.post(
                f"/api/v1/files/{self.project1.id}/{qgis_project_file}/",
                {
                    "file": open(file_path, "rb"),
                },
                format="multipart",
            )
            self.assertTrue(status.is_success(response.status_code))

        jobs = ProcessProjectfileJob.objects.filter(
            project=self.project1,
            status__in=[Job.Status.PENDING, Job.Status.QUEUED, Job.Status.STARTED],
        )

        self.assertEqual(jobs.count(), 1)
