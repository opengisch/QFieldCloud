import io
import logging

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Job,
    PackageJob,
    Person,
    Project,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin

from .utils import (
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]

        # Create a project
        self.p1 = Project.objects.create(name="p1", is_public=False, owner=self.u1)

    def assertLayerData(
        self, layer_data: dict, is_valid: bool, is_localized: bool, error_code: str
    ) -> None:
        self.assertEquals(layer_data["is_valid"], is_valid)
        self.assertEquals(layer_data["is_localized"], is_localized)
        self.assertEquals(layer_data["error_code"], error_code)

    def test_bad_layer_handler_values_for_process_projectfile_job(self):
        # Test that BadLayerHandler is parsing data properly during process projectfile jobs
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project and datasource GPKG files
        response = self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self._upload_file(
            self.u1,
            self.p1,
            "project.qgs",
            io.FileIO(testdata_path("simple_bumblebees_wrong_localized.qgs"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(self.p1)
        processprojectfile_job = Job.objects.filter(
            project=self.p1, type=Job.Type.PROCESS_PROJECTFILE
        ).latest("updated_at")

        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        self.p1.refresh_from_db()

        self.assertIsNotNone(self.p1.project_details)

        # extract layer data from job
        processfile_layers = processprojectfile_job.get_feedback_step_data(
            "project_details"
        )["returns"]["project_details"]["layers_by_id"]

        # "valid" localized layer -> QFC considers it as invalid
        self.assertLayerData(
            processfile_layers["valid_localized_point_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # invalid localized layer
        self.assertLayerData(
            processfile_layers["invalid_localized_polygon_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # invalid layer (datasource does not exist)
        self.assertLayerData(
            processfile_layers["invalid_point_layer_id"],
            is_valid=False,
            is_localized=False,
            error_code="invalid_dataprovider",
        )

    def test_bad_layer_handler_values_for_package_job(self):
        # Test that BadLayerHandler is parsing data properly during package jobs
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project and datasource GPKG files
        response = self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self._upload_file(
            self.u1,
            self.p1,
            "project.qgs",
            io.FileIO(testdata_path("simple_bumblebees_wrong_localized.qgs"), "rb"),
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
        qgis_layers = package_job.get_feedback_step_data("qgis_layers_data")["returns"][
            "layers_by_id"
        ]
        qfield_layers = package_job.get_feedback_step_data("qfield_layer_data")[
            "returns"
        ]["layers_by_id"]

        # "valid" localized layer -> QFC considers it as invalid (QGIS)
        self.assertLayerData(
            qgis_layers["valid_localized_point_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # invalid localized layer (QGIS)
        self.assertLayerData(
            qgis_layers["invalid_localized_polygon_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # "valid" localized layer -> QFC considers it as invalid (QField)
        self.assertLayerData(
            qfield_layers["valid_localized_point_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # invalid localized layer (QField)
        self.assertLayerData(
            qfield_layers["invalid_localized_polygon_layer_id"],
            is_valid=False,
            is_localized=True,
            error_code="localized_dataprovider",
        )

        # invalid layer is not present in qfield layers
        self.assertNotIn("invalid_point_layer_id", qfield_layers)

        # invalid layer (datasource does not exist) (QGIS)
        self.assertLayerData(
            qgis_layers["invalid_point_layer_id"],
            is_valid=False,
            is_localized=False,
            error_code="invalid_dataprovider",
        )
