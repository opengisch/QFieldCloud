import filecmp
import logging
import tempfile
import time

import requests
from django.http.response import HttpResponseRedirect
from qfieldcloud.core import utils
from qfieldcloud.core.models import AuthToken, Project, User
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from .utils import get_filename, testdata_path

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(username="user1", password="abc123")
        self.user1.save()

        self.user2 = User.objects.create_user(username="user2", password="abc123")
        self.user2.save()

        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )
        self.project1.save()

    def tearDown(self):
        # Remove all projects avoiding bulk delete in order to use
        # the overrided delete() function in the model
        for p in Project.objects.all():
            bucket = utils.get_s3_bucket()
            prefix = utils.safe_join("projects/{}/".format(p.id))
            bucket.objects.filter(Prefix=prefix).delete()

            p.delete()

        User.objects.all().delete()
        # Remove credentials
        self.client.credentials()

    def test_push_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

    def test_push_download_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # Pull the file
        response = self.client.get(f"/api/v1/files/{self.project1.id}/file.txt/")

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url, stream=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "file.txt")

        temp_file = tempfile.NamedTemporaryFile()

        with open(temp_file.name, "wb") as f:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path("file.txt")))

    def test_push_download_file_with_path(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/foo/bar/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # Pull the file
        response = self.client.get(
            f"/api/v1/files/{self.project1.id}/foo/bar/file.txt/"
        )

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url, stream=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "foo/bar/file.txt")

        temp_file = tempfile.NamedTemporaryFile()

        with open(temp_file.name, "wb") as f:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path("file.txt")))

    def test_push_list_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/aaa/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        file_path = testdata_path("file2.txt")
        # Push a second file
        response = self.client.post(
            "/api/v1/files/{}/file2.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 2)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["name"])

        self.assertEqual(json[0]["name"], "aaa/file.txt")
        self.assertEqual(json[0]["size"], 13)
        self.assertEqual(json[1]["name"], "file2.txt")
        self.assertEqual(json[1]["size"], 13)
        self.assertEqual(
            json[0]["sha256"],
            "8663bab6d124806b9727f89bb4ab9db4cbcc3862f6bbf22024dfa7212aa4ab7d",
        )
        self.assertEqual(
            json[1]["sha256"],
            "fcc85fb502bd772aa675a0263b5fa665bccd5d8d93349d1dbc9f0f6394dd37b9",
        )

    def test_push_list_file_with_space_in_name(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        project_file = "aaa bbb/project qgis 1.2.qgs"
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/{project_file}/",
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, project_file
        )

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()

        self.assertEqual(json[0]["name"], "aaa bbb/project qgis 1.2.qgs")

    def test_push_list_file_versions(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/aaa/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # Wait 2 seconds to be sure the file timestamps are different
        time.sleep(2)

        file_path = testdata_path("file2.txt")
        # Push another file with the same name (i.e. push another
        # version)
        response = self.client.post(
            "/api/v1/files/{}/aaa/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        versions = sorted(
            response.json()[0]["versions"], key=lambda k: k["last_modified"]
        )

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

        self.assertEqual(versions[0]["size"], 13)
        self.assertEqual(versions[1]["size"], 13)

    def test_push_download_specific_version_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # Wait 2 seconds to be sure the file timestamps are different
        time.sleep(2)

        file_path = testdata_path("file2.txt")
        # Push another file with the same name (i.e. push another
        # version)
        response = self.client.post(
            "/api/v1/files/{}/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # Pull the last file (without version parameter)
        response = self.client.get(f"/api/v1/files/{self.project1.id}/file.txt/")

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url, stream=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "file.txt")

        temp_file = tempfile.NamedTemporaryFile()

        with open(temp_file.name, "wb") as f:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        self.assertFalse(filecmp.cmp(temp_file.name, testdata_path("file.txt")))
        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path("file2.txt")))

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))

        versions = sorted(
            response.json()[0]["versions"], key=lambda k: k["last_modified"]
        )

        # Pull the oldest version
        response = self.client.get(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"version": versions[0]["version_id"]},
        )

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url, stream=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "file.txt")

        temp_file = tempfile.NamedTemporaryFile()

        with open(temp_file.name, "wb") as f:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path("file.txt")))

        # Pull the newest version
        response = self.client.get(
            f"/api/v1/files/{self.project1.id}/file.txt/",
            {"version": versions[1]["version_id"]},
        )

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url, stream=True)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), "file.txt")

        temp_file = tempfile.NamedTemporaryFile()

        with open(temp_file.name, "wb") as f:
            for chunk in response.iter_content():
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

        self.assertTrue(filecmp.cmp(temp_file.name, testdata_path("file2.txt")))

    def test_push_delete_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        file_path = testdata_path("file.txt")
        # Push a file
        response = self.client.post(
            "/api/v1/files/{}/aaa/file.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        file_path = testdata_path("file2.txt")
        # Push a second file
        response = self.client.post(
            "/api/v1/files/{}/file2.txt/".format(self.project1.id),
            {"file": open(file_path, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 2)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 2)

        # Delete a file
        response = self.client.delete(
            "/api/v1/files/{}/aaa/file.txt/".format(self.project1.id)
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)

    def test_one_qgis_project_per_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

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
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename,
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
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename,
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
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename,
            qgis_project_file,
        )

        # Push another QGIS project file
        response = self.client.post(
            "/api/v1/files/{}/foo/bar/file2.qgz/".format(self.project1.id),
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename,
            qgis_project_file,
        )

        response = self.client.delete(
            f"/api/v1/files/{self.project1.id}/{qgis_project_file}/",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

    def test_upload_1mb_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        big_file = tempfile.NamedTemporaryFile()
        with open(big_file.name, "wb") as bf:
            bf.truncate(1024 * 1024 * 1)

        # Push the file
        response = self.client.post(
            "/api/v1/files/{}/bigfile.big/".format(self.project1.id),
            data={"file": open(big_file.name, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)
        self.assertEqual("bigfile.big", response.json()[0]["name"])
        self.assertGreater(response.json()[0]["size"], 1000000)
        self.assertLess(response.json()[0]["size"], 1100000)

    def test_upload_10mb_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 0)
        self.assertEqual(
            Project.objects.get(pk=self.project1.pk).project_filename, None
        )

        big_file = tempfile.NamedTemporaryFile()
        with open(big_file.name, "wb") as bf:
            bf.truncate(1024 * 1024 * 10)

        # Push the file
        response = self.client.post(
            "/api/v1/files/{}/bigfile.big/".format(self.project1.id),
            data={"file": open(big_file.name, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(Project.objects.get(pk=self.project1.pk).files_count, 1)

        # List files
        response = self.client.get("/api/v1/files/{}/".format(self.project1.id))

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(len(response.json()), 1)
        self.assertEqual("bigfile.big", response.json()[0]["name"])
        self.assertGreater(response.json()[0]["size"], 10000000)
        self.assertLess(response.json()[0]["size"], 11000000)
