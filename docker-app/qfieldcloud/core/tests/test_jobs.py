import io
import logging

from django.contrib.gis.geos import Polygon
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Job,
    PackageJob,
    Person,
    Project,
    ProjectSeed,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
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

    def test_has_online_vector_data_with_virtual_layer(self):
        self._upload_files(
            self.u1,
            self.p1,
            files=[
                ("project.qgs", "delta/project_with_virtual.qgs"),
            ],
        )

        wait_for_project_ok_status(self.p1)

        self.p1.refresh_from_db()

        self.assertEqual(self.p1.the_qgis_file_name, "project.qgs")
        self.assertFalse(self.p1.has_online_vector_data)

    def test_has_online_vector_data_with_virtual_layer_with_embedded(self):
        self._upload_files(
            self.u1,
            self.p1,
            files=[
                ("project.qgs", "delta/project_with_virtual_with_embedded.qgs"),
            ],
        )

        wait_for_project_ok_status(self.p1)

        self.p1.refresh_from_db()

        self.assertEqual(self.p1.the_qgis_file_name, "project.qgs")
        self.assertTrue(self.p1.has_online_vector_data)

    def test_create_project_from_xlsform(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        ProjectSeed.objects.create(
            project=self.p1,
            extent=Polygon.from_bbox((-20000000, 20000000, -20000000, 20000000)),
            settings={
                "schemaId": "https://app.qfield.cloud/schemas/project-seed-20251201.json",
                "basemaps": [
                    {
                        "name": "OpenStreetMap (Standard)",
                        "style": "standard",
                        "url": "https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png",
                    }
                ],
                "xlsform": {
                    "show_groups_as_tabs": False,
                },
            },
            xlsform_file=ContentFile(
                open(testdata_path("xlsforms/service_rating.xlsx"), "rb").read(),
                "service_rating.xlsx",
            ),
        )

        Job.objects.create(
            project=self.p1,
            type=Job.Type.CREATE_PROJECT,
            created_by=self.u1,
        )

        wait_for_project_ok_status(self.p1)

        self.p1.refresh_from_db()

        pd = self.p1.project_details

        self.assertIsNotNone(pd)

        self.assertEqual(pd["crs"], "EPSG:3857")
        self.assertEqual(len(pd["layers_by_id"]), 7)

        layers = list(pd["layers_by_id"].values())
        layers.sort(key=lambda layer: layer["name"])

        self.assertEqual(layers[0]["name"], "OpenStreetMap (Standard)")
        self.assertEqual(layers[1]["name"], "list_rating")
        self.assertEqual(layers[1]["wkb_type"], 100)
        self.assertEqual(layers[2]["name"], "list_role")
        self.assertEqual(layers[2]["wkb_type"], 100)
        self.assertEqual(layers[3]["name"], "list_salutation")
        self.assertEqual(layers[3]["wkb_type"], 100)
        self.assertEqual(layers[4]["name"], "list_services")
        self.assertEqual(layers[4]["wkb_type"], 100)
        self.assertEqual(layers[5]["name"], "list_yes_no")
        self.assertEqual(layers[5]["wkb_type"], 100)
        self.assertEqual(layers[6]["name"], "survey")
        self.assertEqual(layers[6]["crs"], "EPSG:4326")
        self.assertEqual(layers[6]["wkb_type"], 4)

        fields = layers[6]["fields"]

        self.assertEqual(len(fields), 22)
        self.assertEqual(fields[0]["name"], "fid")
        self.assertEqual(fields[0]["type"], "Integer64")
        self.assertEqual(fields[1]["name"], "uuid")
        self.assertEqual(fields[1]["type"], "String")
        self.assertEqual(fields[2]["name"], "recommend")
        self.assertEqual(fields[2]["type"], "String")
        self.assertEqual(fields[3]["name"], "services")
        self.assertEqual(fields[3]["type"], "String")
        self.assertEqual(fields[4]["name"], "info_portal_rating")
        self.assertEqual(fields[4]["type"], "String")
        self.assertEqual(fields[5]["name"], "clinical_trials_rating")
        self.assertEqual(fields[5]["type"], "String")
        self.assertEqual(fields[6]["name"], "support_program_rating")
        self.assertEqual(fields[6]["type"], "String")
        self.assertEqual(fields[7]["name"], "ordering_rating")
        self.assertEqual(fields[7]["type"], "String")
        self.assertEqual(fields[8]["name"], "rep_scheduling_rating")
        self.assertEqual(fields[8]["type"], "String")
        self.assertEqual(fields[9]["name"], "cme_rating")
        self.assertEqual(fields[9]["type"], "String")
        self.assertEqual(fields[10]["name"], "feature_improve")
        self.assertEqual(fields[10]["type"], "String")
        self.assertEqual(fields[11]["name"], "part_employees")
        self.assertEqual(fields[11]["type"], "Integer64")
        self.assertEqual(fields[12]["name"], "full_employees")
        self.assertEqual(fields[12]["type"], "Integer64")
        self.assertEqual(fields[13]["name"], "employee_total")
        self.assertEqual(fields[13]["type"], "String")
        self.assertEqual(fields[14]["name"], "employee_summary")
        self.assertEqual(fields[14]["type"], "Boolean")
        self.assertEqual(fields[15]["name"], "salutation")
        self.assertEqual(fields[15]["type"], "String")
        self.assertEqual(fields[16]["name"], "name")
        self.assertEqual(fields[16]["type"], "String")
        self.assertEqual(fields[17]["name"], "address")
        self.assertEqual(fields[17]["type"], "String")
        self.assertEqual(fields[18]["name"], "zip_code")
        self.assertEqual(fields[18]["type"], "String")
        self.assertEqual(fields[19]["name"], "city")
        self.assertEqual(fields[19]["type"], "String")
        self.assertEqual(fields[20]["name"], "state")
        self.assertEqual(fields[20]["type"], "String")
        self.assertEqual(fields[21]["name"], "comment")
        self.assertEqual(fields[21]["type"], "String")
