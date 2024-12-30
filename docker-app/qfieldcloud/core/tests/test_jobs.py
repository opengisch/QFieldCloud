import logging

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Job,
    PackageJob,
    Person,
    ProcessProjectfileJob,
    Project,
)
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APITransactionTestCase

from .utils import (
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)

logging.disable(logging.CRITICAL)

VALID_LOCALIZED_LAYER_KEY = "apiary_853c29cb_ead8_4932_a60a_5cba33140b3d"
INVALID_LAYER_KEY = "apiary_e7d1b542_1b1c_422d_ac75_c14d2b54e472"
INVALID_LOCALIZED_LAYER_KEY = "area_a7b70aff_23f2_4876_9d4e_fa63036df0b2"


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]

        # Create a project
        self.p1 = Project.objects.create(name="p1", is_public=False, owner=self.u1)

    def upload_file(self, project_id: str, local: str, remote: str) -> Response:
        """Upload a file to QFieldCloud using API.

        Args:
            project_id (str): id of the project that should contain the file.
            local (str): name of the local file to upload, should be in `testdata` folder.
            remote (str): name of the uploaded file.

        Returns:
            Response: response to the POST HTTP request.
        """
        file_path = testdata_path(local)
        response = self.client.post(
            f"/api/v1/files/{project_id}/{remote}/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        return response

    def test_bad_layer_handler_values_for_process_projectfile_job(self):
        # Test that BadLayerHandler is parsing data properly during process projectfile jobs
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project and datasource GPKG files
        response = self.upload_file(self.p1.id, "bumblebees.gpkg", "bumblebees.gpkg")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.upload_file(
            self.p1.id, "simple_bumblebees_wrong_localized.qgs", "project.qgs"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Create ProcessProjectfileJob and wait for it to finish
        processprojectfile_job = ProcessProjectfileJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.p1,
            created_by=self.u1,
        )
        self.assertEqual(processprojectfile_job.status, Job.Status.PENDING)
        wait_for_project_ok_status(self.p1)

        processprojectfile_job.refresh_from_db()
        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        self.p1.refresh_from_db()
        self.assertIsNotNone(self.p1.project_details)

        # extract layer data from job
        for step in processprojectfile_job.feedback["steps"]:
            if step["id"] == "project_details":
                processfile_layers = step["returns"]["project_details"]["layers_by_id"]

        # "valid" localized layer -> QFC considers it as invalid
        valid_localized_layer = processfile_layers[VALID_LOCALIZED_LAYER_KEY]
        self.assertFalse(valid_localized_layer["is_valid"])
        self.assertTrue(valid_localized_layer["is_localized"])

        # invalid localized layer
        invalid_localized_layer = processfile_layers[INVALID_LOCALIZED_LAYER_KEY]
        self.assertFalse(invalid_localized_layer["is_valid"])
        self.assertTrue(invalid_localized_layer["is_localized"])
        self.assertEquals(
            invalid_localized_layer["error_code"], "localized_dataprovider"
        )

        # invalid layer (datasource does not exist)
        invalid_layer = processfile_layers[INVALID_LAYER_KEY]
        self.assertFalse(invalid_layer["is_valid"])
        self.assertFalse(invalid_layer["is_localized"])
        self.assertEquals(invalid_layer["error_code"], "invalid_dataprovider")

    def test_bad_layer_handler_values_for_package_job(self):
        # Test that BadLayerHandler is parsing data properly during package jobs
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project and datasource GPKG files
        response = self.upload_file(self.p1.id, "bumblebees.gpkg", "bumblebees.gpkg")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.upload_file(
            self.p1.id, "simple_bumblebees_wrong_localized.qgs", "project.qgs"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Create Package job and wait for it to finish
        set_subscription(
            self.u1,
            "keep_10",
            storage_mb=10,
            is_premium=True,
            is_external_db_supported=True,
        )
        package_job = PackageJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.p1,
            created_by=self.u1,
        )
        self.assertEqual(package_job.status, Job.Status.PENDING)
        wait_for_project_ok_status(self.p1)

        package_job.refresh_from_db()
        self.assertEqual(package_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(package_job.feedback)

        # extract layer data from job
        for step in package_job.feedback["steps"]:
            if step["id"] == "qgis_layers_data":
                qgis_layers = step["returns"]["layers_by_id"]
            if step["id"] == "qfield_layer_data":
                qfield_layers = step["returns"]["layers_by_id"]

        for layers in [qgis_layers, qfield_layers]:
            # "valid" localized layer -> QFC considers it as invalid
            valid_localized_layer = layers[VALID_LOCALIZED_LAYER_KEY]
            self.assertFalse(valid_localized_layer["is_valid"])
            self.assertTrue(valid_localized_layer["is_localized"])

            # invalid localized layer
            invalid_localized_layer = layers[INVALID_LOCALIZED_LAYER_KEY]
            self.assertFalse(invalid_localized_layer["is_valid"])
            self.assertTrue(invalid_localized_layer["is_localized"])
            self.assertEquals(
                invalid_localized_layer["error_code"], "localized_dataprovider"
            )

        # invalid layer is not present in qfield layers
        self.assertNotIn(INVALID_LAYER_KEY, qfield_layers)

        # invalid layer (datasource does not exist)
        invalid_layer = qgis_layers[INVALID_LAYER_KEY]
        self.assertFalse(invalid_layer["is_valid"])
        self.assertFalse(invalid_layer["is_localized"])
        self.assertEquals(invalid_layer["error_code"], "invalid_dataprovider")
