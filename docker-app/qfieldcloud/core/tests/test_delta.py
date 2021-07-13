import io
import json
import logging
import os
import sqlite3
import tempfile
import time

import fiona
import requests
import rest_framework
from django.http.response import HttpResponseRedirect
from qfieldcloud.core import utils
from qfieldcloud.core.models import Project, ProjectCollaborator, User
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITransactionTestCase

from .utils import get_filename, testdata_path

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):

    DJANGO_BASE_URL = "http://localhost:8000/api/v1/"

    def setUp(self):
        # Check if orchestrator is running otherwise skip test
        if not utils.redis_is_running():
            self.skipTest("Redis is not running correctly")

        # Create a user
        self.user1 = User.objects.create_user(username="user1", password="abc123")
        self.user1.save()
        self.user2 = User.objects.create_user(username="user2", password="abc123")
        self.user2.save()
        self.user3 = User.objects.create_user(username="user3", password="abc123")
        self.user3.save()

        self.token1 = Token.objects.get_or_create(user=self.user1)[0]
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]
        self.token3 = Token.objects.get_or_create(user=self.user3)[0]

        # Create a project
        self.project1 = Project.objects.create(
            id="e02d02cc-af1b-414c-a14c-e2ed5dfee52f",
            name="project1",
            is_public=False,
            owner=self.user1,
        )
        self.project1.save()

        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user2,
            role=ProjectCollaborator.Roles.REPORTER,
        )
        ProjectCollaborator.objects.create(
            project=self.project1,
            collaborator=self.user3,
            role=ProjectCollaborator.Roles.ADMIN,
        )

    def tearDown(self):
        # Remove credentials
        self.client.credentials()

    @classmethod
    def tearDownClass(cls):
        # Remove all projects avoiding bulk delete in order to use
        # the overridden delete() function in the model
        for p in Project.objects.all():
            bucket = utils.get_s3_bucket()
            prefix = utils.safe_join(f"projects/{p.id}/")
            bucket.objects.filter(Prefix=prefix).delete()

            p.delete()

        User.objects.all().delete()

    def upload_project_files(self):
        # Verify the original geojson file
        with open(testdata_path("delta/points.geojson")) as f:
            points_geojson = json.load(f)
            features = sorted(points_geojson["features"], key=lambda k: k["id"])
            self.assertEqual(1, features[0]["properties"]["int"])

        for project_file in [
            "points.geojson",
            "polygons.geojson",
            "testdata.gpkg",
            "project.qgs",
            "nonspatial.csv",
        ]:
            file_path = testdata_path(f"delta/{project_file}")
            response = self.client.post(
                f"/api/v1/files/{self.project1.id}/{project_file}/",
                {"file": open(file_path, "rb")},
                format="multipart",
            )
            self.assertTrue(
                status.is_success(response.status_code),
                f"Failed to upload file '{project_file}'",
            )

    def test_push_apply_delta_file(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta2.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                "/api/v1/deltas/{}/".format(self.project1.id),
            )

            if response.json()[0]["status"] in ["STATUS_BUSY", "STATUS_PENDING"]:
                continue

            self.assertEqual("STATUS_APPLIED", response.json()[0]["status"])

            gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
            with fiona.open(gpkg, layer="points") as layer:
                features = list(layer)
                self.assertEqual(666, features[0]["properties"]["int"])

            return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_with_error(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/with_errors.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                "/api/v1/deltas/{}/".format(self.project1.id),
            )

            if response.json()[0]["status"] == "STATUS_BUSY":
                continue

            self.assertEqual("STATUS_NOT_APPLIED", response.json()[0]["status"])
            return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_invalid_json_schema(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        bucket = utils.get_s3_bucket()
        prefix = utils.safe_join(f"projects/{self.project1.id}/deltas/")
        wrong_deltas_before = list(bucket.objects.filter(Prefix=prefix))

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/not_schema_valid.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertFalse(status.is_success(response.status_code))

        # check it is uploaded
        wrong_deltas = list(bucket.objects.filter(Prefix=prefix))

        # TODO : cleanup buckets before in setUp so tests are completely independent
        self.assertEqual(len(wrong_deltas), len(wrong_deltas_before) + 1)

        with open(delta_file, "rb") as f:
            self.assertEqual(wrong_deltas[-1].get()["Body"].read(), f.read())

    def test_push_apply_delta_file_not_json(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a wrong deltafile
        delta_file = testdata_path("file.txt")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertFalse(status.is_success(response.status_code))

    def test_push_apply_delta_file_conflicts_overwrite_true(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta_conflict.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                "/api/v1/deltas/{}/".format(self.project1.id),
            )

            if response.json()[0]["status"] == "STATUS_BUSY":
                continue

            self.assertEqual("STATUS_APPLIED", response.json()[0]["status"])
            return

        self.fail("Worker didn't finish")

    def test_push_apply_delta_file_twice(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                "/api/v1/deltas/{}/".format(self.project1.id),
            )

            if response.json()[0]["status"] == "STATUS_BUSY":
                continue

            self.assertEqual("STATUS_APPLIED", response.json()[0]["status"])

            response = self.client.get(
                f"/api/v1/files/{self.project1.id}/testdata.gpkg/"
            )

            self.assertIsInstance(response, HttpResponseRedirect)

            response = requests.get(response.url, stream=True)

            self.assertTrue(status.is_success(response.status_code))
            self.assertEqual(get_filename(response), "testdata.gpkg")

            temp_dir = tempfile.mkdtemp()
            local_file = os.path.join(temp_dir, "testdata.gpkg")

            with open(local_file, "wb") as f:
                for chunk in response.iter_content():
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)

            conn = sqlite3.connect(local_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""SELECT * FROM points WHERE fid = 1""")
            f = c.fetchone()

            self.assertEqual(666, f["int"])
            return

        # Push the same deltafile again
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta.json")

        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push a deltafile with same id but different content
        delta_file = testdata_path(
            "delta/deltas/singlelayer_singledelta_diff_content.json"
        )

        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_client_error(response.status_code))

    def test_push_list_deltas(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta3.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push another deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta4.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get("/api/v1/deltas/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        self.assertEqual(len(json), 2)
        json = sorted(json, key=lambda k: k["id"])

        self.assertEqual(json[0]["id"], "802ae2ef-f360-440e-a816-8990d6a06667")
        self.assertIn(json[0]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[0]["created_by"], self.user1.username)
        self.assertEqual(json[1]["id"], "e4546ec2-6e01-43a1-ab30-a52db9469afd")
        self.assertIn(json[0]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[1]["created_by"], self.user1.username)

    def test_push_list_multidelta(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_multidelta.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get("/api/v1/deltas/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        json = sorted(json, key=lambda k: k["id"])

        self.assertEqual(json[0]["id"], "736bf2c2-646a-41a2-8c55-28c26aecd68d")
        self.assertIn(json[0]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[0]["created_by"], self.user1.username)
        self.assertEqual(json[1]["id"], "8adac0df-e1d3-473e-b150-f8c4a91b4781")
        self.assertIn(json[1]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[1]["created_by"], self.user1.username)
        self.assertEqual(json[2]["id"], "c6c88e78-172c-4f77-b2fd-2ff41f5aa854")
        self.assertIn(json[2]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[2]["created_by"], self.user1.username)

    def test_push_list_deltas_of_deltafile(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta5.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Push another deltafile
        delta_file = testdata_path("delta/deltas/singlelayer_singledelta6.json")
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Get all deltas
        response = self.client.get("/api/v1/deltas/{}/".format(self.project1.id))
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        self.assertEqual(len(json), 2)
        json = sorted(json, key=lambda k: k["id"])

        self.assertEqual(json[0]["id"], "ad98634e-509f-4dff-9000-de79b09c5359")
        self.assertIn(json[0]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[0]["created_by"], self.user1.username)
        self.assertEqual(json[1]["id"], "df6a19eb-7d61-4c64-9e3b-29bce0a8dfab")
        self.assertIn(json[1]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[1]["created_by"], self.user1.username)

        # Get only deltas of one deltafile
        response = self.client.get(
            "/api/v1/deltas/{}/{}/".format(
                self.project1.id, "3aab7e58-ea27-4b7c-9bca-c772b6d94820"
            )
        )
        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        self.assertEqual(len(json), 1)
        self.assertEqual(json[0]["id"], "ad98634e-509f-4dff-9000-de79b09c5359")
        self.assertIn(json[0]["status"], ["STATUS_PENDING", "STATUS_BUSY"])
        self.assertEqual(json[0]["created_by"], self.user1.username)
        self.assertIn("output", json[0])

    def test_push_apply_delta_file_conflicts_overwrite_false(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Set the overwrite_conflicts flag to False
        self.project1.overwrite_conflicts = False
        self.project1.save()

        # Push a deltafile
        delta_file = testdata_path(
            "delta/deltas/singlelayer_singledelta_conflict2.json"
        )
        response = self.client.post(
            "/api/v1/deltas/{}/".format(self.project1.id),
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            response = self.client.get(
                "/api/v1/deltas/{}/".format(self.project1.id),
            )

            if response.json()[0]["status"] == "STATUS_BUSY":
                continue

            self.assertEqual("STATUS_CONFLICT", response.json()[0]["status"])
            return

        self.fail("Worker didn't finish")

    def test_list_deltas_unexisting_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        response = self.client.get(
            "/api/v1/deltas/7199612e-7641-48fc-8c11-c25176a9761b/"
        )
        self.assertFalse(status.is_success(response.status_code))
        json = response.json()
        self.assertEqual(json["code"], "object_not_found")

    def test_push_delta_not_allowed(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token2.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path(
            "delta/deltas/singlelayer_multidelta_patch_create.json"
        )
        response = self.client.post(
            f"/api/v1/deltas/{self.project1.id}/",
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(f"/api/v1/deltas/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        json = sorted(json, key=lambda k: k["id"])

        self.assertEqual(json[0]["id"], "736bf2c2-646a-41a2-8c55-28c26aecd68d")
        self.assertEqual(json[0]["status"], "STATUS_UNPERMITTED")
        self.assertEqual(json[0]["created_by"], self.user2.username)
        self.assertEqual(json[1]["id"], "8adac0df-e1d3-473e-b150-f8c4a91b4781")
        self.assertEqual(json[1]["status"], "STATUS_UNPERMITTED")
        self.assertEqual(json[1]["created_by"], self.user2.username)

    def test_non_spatial_delta(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # Push a deltafile
        delta_file = testdata_path("delta/deltas/nonspatial.json")
        response = self.client.post(
            f"/api/v1/deltas/{self.project1.id}/",
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        response = self.client.get(f"/api/v1/deltas/{self.project1.id}/")
        self.assertTrue(status.is_success(response.status_code))
        json = response.json()
        json = sorted(json, key=lambda k: k["id"])

        self.assertEqual(json[0]["id"], "1270b97d-6a28-49cc-83f3-b827ec574fee")
        self.assertIn(json[0]["status"], ["STATUS_BUSY", "STATUS_PENDING"])
        self.assertEqual(json[0]["created_by"], self.user1.username)
        self.assertEqual(json[1]["id"], "f326c3c1-138f-4261-9151-4946237ce714")
        self.assertIn(json[1]["status"], ["STATUS_BUSY", "STATUS_PENDING"])
        self.assertEqual(json[1]["created_by"], self.user1.username)

        for _ in range(30):
            time.sleep(2)
            response = self.client.get(f"/api/v1/deltas/{self.project1.id}/")
            json = response.json()
            json = sorted(json, key=lambda k: k["id"])

            if json[0]["status"] in ["STATUS_BUSY", "STATUS_PENDING"] or json[1][
                "status"
            ] in ["STATUS_BUSY", "STATUS_PENDING"]:
                continue

            response = self.client.get(
                f"/api/v1/files/{self.project1.id}/nonspatial.csv/"
            )

            self.assertIsInstance(response, HttpResponseRedirect)

            response = requests.get(response.url)

            self.assertTrue(status.is_success(response.status_code))
            self.assertEqual(get_filename(response), "nonspatial.csv")

            self.assertEqual(response.content, b'fid,col1\n"1",qux\n')

            return

    def test_apply222(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        self.upload_project_files()

        # 1) client 1 creates a feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p1_c1_create.json",
            token=self.token1.key,
            final_values=[
                [
                    "9311eb96-bff8-4d5b-ab36-c314a007cfcd",
                    "STATUS_APPLIED",
                    self.user1.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 4)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)
            self.assertEqual(features[3]["properties"]["int"], 1000)

        # 2) client 2 creates a feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p2_c2_create.json",
            token=self.token3.key,
            final_values=[
                [
                    "608bbfb7-fb9c-49c4-818f-f636ee4ec20a",
                    "STATUS_APPLIED",
                    self.user3.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 5)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)
            self.assertEqual(features[3]["properties"]["int"], 1000)
            self.assertEqual(features[4]["properties"]["int"], 2000)

        # 3) client 1 updates their created feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p3_c1_patch.json",
            token=self.token3.key,
            final_values=[
                [
                    "f11603e5-13b2-43a9-b27a-db722297773b",
                    "STATUS_APPLIED",
                    self.user3.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 5)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)
            self.assertEqual(features[3]["properties"]["int"], 1001)
            self.assertEqual(features[4]["properties"]["int"], 2000)

        # 4) client 2 updates their created feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p4_c2_patch.json",
            token=self.token3.key,
            final_values=[
                [
                    "582de6de-562f-4482-9350-5b5aaa25d822",
                    "STATUS_APPLIED",
                    self.user3.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 5)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)
            self.assertEqual(features[3]["properties"]["int"], 1001)
            self.assertEqual(features[4]["properties"]["int"], 2002)

        # 5) client 1 deletes their created feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p5_c1_delete.json",
            token=self.token3.key,
            final_values=[
                [
                    "b7a09a1d-9626-4da0-8456-61c2ff884611",
                    "STATUS_APPLIED",
                    self.user3.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 4)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)
            self.assertEqual(features[3]["properties"]["int"], 2002)

        # 6) client 2 deletes their created feature
        self.upload_deltafile(
            project=self.project1,
            delta_filename="multistage_p6_c2_delete.json",
            token=self.token3.key,
            final_values=[
                [
                    "7cb988e9-5de2-4bd7-af4b-c1d27a2d579f",
                    "STATUS_APPLIED",
                    self.user3.username,
                ]
            ],
        )

        gpkg = io.BytesIO(self.get_file_contents(self.project1, "testdata.gpkg"))
        with fiona.open(gpkg, "r", layer="points") as layer:
            features = list(layer)

            self.assertEqual(len(features), 3)
            self.assertEqual(features[0]["properties"]["int"], 1)
            self.assertEqual(features[1]["properties"]["int"], 2)
            self.assertEqual(features[2]["properties"]["int"], 3)

    def get_file_contents(self, project, filename):
        response = self.client.get(f"/api/v1/files/{project.id}/{filename}/")

        self.assertIsInstance(response, HttpResponseRedirect)

        response = requests.get(response.url)

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(get_filename(response), filename)

        return response.content

    def upload_deltafile(
        self,
        project,
        delta_filename,
        final_values,
        token,
        wait_status=["STATUS_PENDING", "STATUS_BUSY"],
        failing_status=["STATUS_ERROR"],
        immediate_values=None,
    ):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token)

        # Push a deltafile
        delta_file = testdata_path(f"delta/deltas/{delta_filename}")
        with open(delta_file) as f:
            deltafile_id = json.load(f)["id"]

        response = self.client.post(
            f"/api/v1/deltas/{project.id}/",
            {"file": open(delta_file, "rb")},
            format="multipart",
        )
        self.assertTrue(rest_framework.status.is_success(response.status_code))

        response = self.client.get(f"/api/v1/deltas/{project.id}/{deltafile_id}/")
        self.assertTrue(rest_framework.status.is_success(response.status_code))
        payload = response.json()
        payload = sorted(payload, key=lambda k: k["id"])

        if immediate_values:
            self.assertEqual(len(payload), len(immediate_values))

            for idx, immediate_value in enumerate(immediate_values):
                delta_id, status, created_by = immediate_value
                status = status if isinstance(status, list) else list(status)

                self.assertEqual(payload[idx]["id"], delta_id)
                self.assertIn(payload[idx]["status"], status)
                self.assertEqual(payload[idx]["created_by"], created_by)

        for _ in range(10):

            time.sleep(2)
            response = self.client.get(f"/api/v1/deltas/{project.id}/{deltafile_id}/")

            payload = response.json()
            payload = sorted(payload, key=lambda k: k["id"])

            self.assertEqual(len(payload), len(final_values))

            for idx, final_value in enumerate(final_values):
                if payload[idx]["status"] in wait_status:
                    break

                if payload[idx]["status"] in failing_status:
                    self.fail(f"Got failing status {payload[idx]['status']}")
                    return

                delta_id, status, created_by = final_value
                status = status if isinstance(status, list) else [status]

                self.assertEqual(payload[idx]["id"], delta_id)
                self.assertIn(payload[idx]["status"], status)
                self.assertEqual(payload[idx]["created_by"], created_by)
                return

        self.fail("Worker didn't finish")
