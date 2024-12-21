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

    def test_create_job_bad_layer_handler_extracted_values(self):
        # Test that BadLayerHandler is parsing data properly during package and process projectfile jobs
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project and datasource GPKG files
        for local_filename, upload_filename in [
            ("bumblebees.gpkg", "bumblebees.gpkg"),
            ("simple_bumblebees_wrong_localized.qgs", "project.qgs"),
        ]:
            file_path = testdata_path(local_filename)
            response = self.client.post(
                f"/api/v1/files/{self.p1.id}/{upload_filename}/",
                {
                    "file": open(file_path, "rb"),
                },
                format="multipart",
            )
            self.assertTrue(status.is_success(response.status_code))

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

        # extract layer data from both jobs
        for step in processprojectfile_job.feedback["steps"]:
            if step["id"] == "project_details":
                processfile_layers = step["returns"]["project_details"]["layers_by_id"]
        for step in package_job.feedback["steps"]:
            if step["id"] == "qgis_layers_data":
                qgis_layers = step["returns"]["layers_by_id"]
            if step["id"] == "qfield_layer_data":
                qfield_layers = step["returns"]["layers_by_id"]

        for layers in [processfile_layers, qgis_layers, qfield_layers]:
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
        assert INVALID_LAYER_KEY not in qfield_layers

        for layers in [
            processfile_layers,
            qgis_layers,
        ]:
            # invalid layer (datasource does not exist)
            invalid_layer = layers[INVALID_LAYER_KEY]
            self.assertFalse(invalid_layer["is_valid"])
            self.assertFalse(invalid_layer["is_localized"])
            self.assertEquals(invalid_layer["error_code"], "invalid_dataprovider")
