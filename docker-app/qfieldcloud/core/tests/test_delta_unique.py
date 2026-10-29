import io
import json
import logging
import tempfile

import geopandas as gpd
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import Delta, Organization, Person
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

# delta ids used in the `unique_constraint_*.json` delta files
DELTA_UUID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DELTA_UUID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DELTA_UUID_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
DELTA_UUID_D = "dddddddd-dddd-dddd-dddd-dddddddddddd"

UUID_1 = "00000000-0000-0000-0000-000000000001"
UUID_2 = "00000000-0000-0000-0000-000000000002"
UUID_3 = "00000000-0000-0000-0000-000000000003"


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user = Person.objects.create_user(
            username="user1", password="the_password_of_user1"
        )
        self.org = Organization.objects.create(
            username="org1", organization_owner=self.user
        )

        self.project = Project.objects.create(name="project1", owner=self.org)

        # upload the test data files for the project
        for filename in ["unique_constraints.gpkg", "project_unique_constraints.qgs"]:
            with open(testdata_path(f"delta/{filename}"), "rb") as f:
                response = self._upload_file(self.user, self.project, filename, f)

            self.assertTrue(status.is_success(response.status_code))

        wait_for_project_ok_status(self.project)

    def push_and_check_deltas(
        self, delta_filename: str, expected_statuses: dict
    ) -> None:
        """Pushes the deltafile, waits for the apply job and checks the resulting delta statuses.

        Every conflict is expected to be a unique constraint conflict.
        """
        with open(testdata_path(f"delta/deltas/{delta_filename}")) as f:
            deltafile = json.load(f)

        deltafile["project"] = str(self.project.id)

        token = self._get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post(
            f"/api/v1/deltas/{self.project.id}/",
            {"file": io.StringIO(json.dumps(deltafile))},
            format="multipart",
        )

        self.client.credentials(HTTP_AUTHORIZATION="")

        self.assertTrue(status.is_success(response.status_code), response.content)

        wait_for_project_ok_status(self.project)

        statuses = {}

        for delta in Delta.objects.filter(deltafile_id=deltafile["id"]):
            statuses[str(delta.id)] = delta.last_status

        self.assertEqual(
            statuses,
            expected_statuses,
        )

    def test_unique_uuid_constraint_with_create_conflict_behavior(self):
        # unique constraint conflicts are raised even with `overwrite_conflicts`
        self.assertTrue(self.project.overwrite_conflicts)
        self.assertEqual(
            self.project.unique_constraint_delta_behavior,
            Project.UniqueConstraintDeltaBehavior.CREATE_CONFLICT,
        )

        self.push_and_check_deltas(
            "unique_constraint_uuid.json",
            {
                DELTA_UUID_A: Delta.Status.CONFLICT,
                DELTA_UUID_B: Delta.Status.CONFLICT,
                DELTA_UUID_C: Delta.Status.APPLIED,
                DELTA_UUID_D: Delta.Status.APPLIED,
            },
        )

        response = self._download_file(
            self.user, self.project, "unique_constraints.gpkg"
        )

        with tempfile.NamedTemporaryFile(suffix=".gpkg") as temp_gpkg:
            temp_gpkg.write(b"".join(response.streaming_content))
            temp_gpkg.flush()
            gdf = gpd.read_file(temp_gpkg.name, layer="points_uuid")

        gpkg_values = sorted(zip(gdf["uuid"], gdf["name"]))

        self.assertEqual(
            gpkg_values,
            [(UUID_1, "first"), (UUID_2, "renamed"), (UUID_3, "created")],
        )

    def test_unique_fid_with_fid_1_pk_create_conflict(self):
        self.push_and_check_deltas(
            "unique_constraint_fid.json",
            {
                DELTA_UUID_A: Delta.Status.CONFLICT,
                DELTA_UUID_B: Delta.Status.CONFLICT,
                DELTA_UUID_C: Delta.Status.APPLIED,
                DELTA_UUID_D: Delta.Status.APPLIED,
            },
        )

        response = self._download_file(
            self.user, self.project, "unique_constraints.gpkg"
        )

        with tempfile.NamedTemporaryFile(suffix=".gpkg") as temp_gpkg:
            temp_gpkg.write(b"".join(response.streaming_content))
            temp_gpkg.flush()
            gdf = gpd.read_file(temp_gpkg.name, layer="points_fid")

        gpkg_values = zip(gdf["fid"], gdf["name"])

        self.assertEqual(
            sorted(gpkg_values),
            [(10, "first"), (30, "created"), (40, "second")],
        )

    def test_unique_constraint_with_qgis_default_behavior(self):
        self.project.unique_constraint_delta_behavior = (
            Project.UniqueConstraintDeltaBehavior.QGIS_DEFAULT
        )
        self.project.save()

        # QGIS only replaces duplicated values on create,
        # on patch: the geopackage unique constraint makes the commit fail, so the deltas C & D not applied
        self.push_and_check_deltas(
            "unique_constraint_qgis_default.json",
            {
                DELTA_UUID_A: Delta.Status.APPLIED,
                DELTA_UUID_B: Delta.Status.APPLIED,
                DELTA_UUID_C: Delta.Status.NOT_APPLIED,
                DELTA_UUID_D: Delta.Status.NOT_APPLIED,
            },
        )

        response = self._download_file(
            self.user, self.project, "unique_constraints.gpkg"
        )

        with tempfile.NamedTemporaryFile(suffix=".gpkg") as temp_gpkg:
            temp_gpkg.write(b"".join(response.streaming_content))
            temp_gpkg.flush()
            gdf_uuid = gpd.read_file(temp_gpkg.name, layer="points_uuid")
            gdf_fid = gpd.read_file(temp_gpkg.name, layer="points_fid")

        # QGIS silently replaces the duplicated values with unique ones
        gpkg_uuid_values = zip(gdf_uuid["uuid"], gdf_uuid["name"])

        self.assertEqual(
            sorted(gpkg_uuid_values),
            [(UUID_1, "first"), (UUID_2, "second"), (f"{UUID_2}_1", "duplicate")],
        )

        gpkg_fid_values = zip(gdf_fid["fid"], gdf_fid["name"])

        self.assertEqual(
            sorted(gpkg_fid_values),
            [(10, "first"), (20, "second"), (21, "duplicate")],
        )
