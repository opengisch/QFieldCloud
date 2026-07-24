import io
import logging

from django.contrib.gis.geos import Polygon
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Job,
    Organization,
    PackageJob,
    Person,
    ProcessProjectfileJob,
    ProjectCollaborator,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.core.utils2.jobs import queue_job
from qfieldcloud.project.enums import QgsGeometryType
from qfieldcloud.project.models import Project, ProjectSeed
from qfieldcloud.project.utils import projectseed_utils

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.u1 = Person.objects.create_user(username="u1", password="abc123")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]

        # Create a project
        self.p1 = Project.objects.create(name="p1", is_public=False, owner=self.u1)

    def refresh_project(self, project: Project) -> None:
        project.refresh_from_db(
            from_queryset=Project.objects.select_related("the_qgis_file")
        )

    def assertLayerData(
        self, layer_data: dict, is_valid: bool, is_localized: bool, error_code: str
    ) -> None:
        self.assertEqual(layer_data["is_valid"], is_valid)
        self.assertEqual(layer_data["is_localized"], is_localized)
        self.assertEqual(layer_data["error_code"], error_code)

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

        # the same layer data should also be synced into the relational `Layer` model
        self.assertTrue(self.p1.qgis_project.layers.exists())

        layer = self.p1.qgis_project.layers.get(
            qgis_layer_id="valid_localized_point_layer_id"
        )
        self.assertFalse(layer.is_valid)
        self.assertTrue(layer.is_localized)
        self.assertEqual(layer.error_code, "localized_dataprovider")

        layer = self.p1.qgis_project.layers.get(
            qgis_layer_id="invalid_localized_polygon_layer_id"
        )
        self.assertFalse(layer.is_valid)
        self.assertTrue(layer.is_localized)
        self.assertEqual(layer.error_code, "localized_dataprovider")

        layer = self.p1.qgis_project.layers.get(qgis_layer_id="invalid_point_layer_id")
        self.assertFalse(layer.is_valid)
        self.assertFalse(layer.is_localized)
        self.assertEqual(layer.error_code, "invalid_dataprovider")

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

        self.refresh_project(self.p1)

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

        self.refresh_project(self.p1)

        self.assertEqual(self.p1.the_qgis_file_name, "project.qgs")
        self.assertTrue(self.p1.has_online_vector_data)

    def test_cannot_create_job_on_project_without_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        u2 = Person.objects.create_user(username="u2", password="abc123")
        p2 = Project.objects.create(is_public=False, owner=u2)

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": p2.id,
                "type": "process_projectfile",
            },
        )

        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": self.p1.id,
                "type": "process_projectfile",
            },
        )

        self.assertEqual(response.status_code, 201)

    def test_can_create_and_read_job_created_by_their_own(self):
        for idx, role in enumerate(ProjectCollaborator.Roles):
            user = Person.objects.create_user(
                username=f"collaborator_{idx}", password="abc123"
            )

            ProjectCollaborator.objects.create(
                project=self.p1,
                collaborator=user,
                role=role,
            )

            token = AuthToken.objects.get_or_create(user=user)[0]

            self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

            resp_post = self.client.post(
                "/api/v1/jobs/",
                {
                    "project_id": self.p1.id,
                    "type": "process_projectfile",
                },
            )

            if role == ProjectCollaborator.Roles.READER:
                self.assertEqual(resp_post.status_code, status.HTTP_403_FORBIDDEN)
                continue

            self.assertTrue(status.is_success(resp_post.status_code))
            self.assertIn("id", resp_post.data)

            job_id = resp_post.data["id"]

            resp_get = self.client.get(
                "/api/v1/jobs/",
                {
                    "project_id": self.p1.id,
                },
            )

            self.assertTrue(status.is_success(resp_get.status_code))
            self.assertGreaterEqual(len(resp_get.data), 1)
            self.assertEqual(resp_get.data[-1]["id"], job_id)

            resp_get = self.client.get(
                f"/api/v1/jobs/{job_id}/",
            )

            self.assertTrue(status.is_success(resp_get.status_code))
            self.assertEqual(resp_get.data["id"], job_id)

    def test_create_project_from_xlsform(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        ProjectSeed.objects.create(
            project=self.p1,
            extent=Polygon.from_bbox(projectseed_utils.DEFAULT_PROJECT_EXTENT),
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

        layers = list(self.p1.qgis_project.layers.all())
        layers.sort(key=lambda layer: layer.name)

        self.assertEqual(len(layers), 7)
        self.assertEqual(layers[0].name, "OpenStreetMap (Standard)")
        self.assertEqual(layers[1].name, "Survey")
        self.assertEqual(layers[1].crs, "EPSG:3857")
        # wkb_type 4 = MultiPoint -> geometryType() = Point
        self.assertEqual(layers[1].geom_type, QgsGeometryType.Point)
        self.assertEqual(layers[2].name, "list_rating")
        # wkb_type 100 = NoGeometry
        self.assertEqual(layers[2].geom_type, QgsGeometryType.Null)
        self.assertEqual(layers[3].name, "list_role")
        self.assertEqual(layers[3].geom_type, QgsGeometryType.Null)
        self.assertEqual(layers[4].name, "list_salutation")
        self.assertEqual(layers[4].geom_type, QgsGeometryType.Null)
        self.assertEqual(layers[5].name, "list_services")
        self.assertEqual(layers[5].geom_type, QgsGeometryType.Null)
        self.assertEqual(layers[6].name, "list_yes_no")
        self.assertEqual(layers[6].geom_type, QgsGeometryType.Null)

        # TODO @suricactus: The fields will be present again once `Layer` and `LayerField` models are implemented as the data will no longer fatten the `Project` model, see https://app.clickup.com/t/2192114/QF-8219
        # fields = layers[6]["fields"]

        # self.assertEqual(len(fields), 22)
        # self.assertEqual(fields[0]["name"], "fid")
        # self.assertEqual(fields[0]["type"], "Integer64")
        # self.assertEqual(fields[1]["name"], "uuid")
        # self.assertEqual(fields[1]["type"], "String")
        # self.assertEqual(fields[2]["name"], "recommend")
        # self.assertEqual(fields[2]["type"], "String")
        # self.assertEqual(fields[3]["name"], "services")
        # self.assertEqual(fields[3]["type"], "String")
        # self.assertEqual(fields[4]["name"], "info_portal_rating")
        # self.assertEqual(fields[4]["type"], "String")
        # self.assertEqual(fields[5]["name"], "clinical_trials_rating")
        # self.assertEqual(fields[5]["type"], "String")
        # self.assertEqual(fields[6]["name"], "support_program_rating")
        # self.assertEqual(fields[6]["type"], "String")
        # self.assertEqual(fields[7]["name"], "ordering_rating")
        # self.assertEqual(fields[7]["type"], "String")
        # self.assertEqual(fields[8]["name"], "rep_scheduling_rating")
        # self.assertEqual(fields[8]["type"], "String")
        # self.assertEqual(fields[9]["name"], "cme_rating")
        # self.assertEqual(fields[9]["type"], "String")
        # self.assertEqual(fields[10]["name"], "feature_improve")
        # self.assertEqual(fields[10]["type"], "String")
        # self.assertEqual(fields[11]["name"], "part_employees")
        # self.assertEqual(fields[11]["type"], "Integer64")
        # self.assertEqual(fields[12]["name"], "full_employees")
        # self.assertEqual(fields[12]["type"], "Integer64")
        # self.assertEqual(fields[13]["name"], "employee_total")
        # self.assertEqual(fields[13]["type"], "String")
        # self.assertEqual(fields[14]["name"], "employee_summary")
        # self.assertEqual(fields[14]["type"], "Boolean")
        # self.assertEqual(fields[15]["name"], "salutation")
        # self.assertEqual(fields[15]["type"], "String")
        # self.assertEqual(fields[16]["name"], "name")
        # self.assertEqual(fields[16]["type"], "String")
        # self.assertEqual(fields[17]["name"], "address")
        # self.assertEqual(fields[17]["type"], "String")
        # self.assertEqual(fields[18]["name"], "zip_code")
        # self.assertEqual(fields[18]["type"], "String")
        # self.assertEqual(fields[19]["name"], "city")
        # self.assertEqual(fields[19]["type"], "String")
        # self.assertEqual(fields[20]["name"], "state")
        # self.assertEqual(fields[20]["type"], "String")
        # self.assertEqual(fields[21]["name"], "comment")
        # self.assertEqual(fields[21]["type"], "String")

    def test_thumbnail_generation_with_wrong_extent_does_not_hang(self):
        # Test that if the thumbnail generation hangs forever (e.g. due to invalid extent), the job is cancelled after the timeout and the project is still processed successfully.
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        # Push the QGIS project file with invalid extent
        response = self._upload_file(
            self.u1,
            self.p1,
            "project.qgs",
            io.FileIO(testdata_path("project_with_invalid_extent.qgs"), "rb"),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(self.p1)

        self.refresh_project(self.p1)

        self.assertEqual(self.p1.the_qgis_file_name, "project.qgs")
        self.assertEqual(self.p1.thumbnail.name, "")

    def test_clone_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        ProjectSeed.objects.create(
            project=self.p1,
            extent=Polygon.from_bbox(projectseed_utils.DEFAULT_PROJECT_EXTENT),
            settings={
                "schemaId": ProjectSeed.SETTINGS_SCHEMA_ID,
                "basemaps": [],
                "xlsform": None,
            },
        )

        Job.objects.create(
            project=self.p1,
            type=Job.Type.CREATE_PROJECT,
            created_by=self.u1,
        )

        wait_for_project_ok_status(self.p1)

        # Clone the project

        cloned_project = Project.objects.create(
            name="cloned_project",
            owner=self.u1,
            is_public=False,
            overwrite_conflicts=True,
            has_restricted_projectfiles=True,
            is_attachment_download_on_demand=True,
        )

        ProjectSeed.objects.create(
            project=cloned_project,
            extent=Polygon.from_bbox(projectseed_utils.DEFAULT_PROJECT_EXTENT),
            clone_from_project=self.p1,
            settings={
                "schemaId": ProjectSeed.SETTINGS_SCHEMA_ID,
                "basemaps": [],
                "xlsform": None,
            },
        )

        Job.objects.create(
            project=cloned_project,
            type=Job.Type.CREATE_PROJECT,
            created_by=self.u1,
        )

        wait_for_project_ok_status(cloned_project)

        self.refresh_project(self.p1)
        self.refresh_project(cloned_project)

        # compare project files
        source_response = self._list_files(self.u1, self.p1)
        cloned_response = self._list_files(self.u1, cloned_project)

        self.assertEqual(source_response.status_code, status.HTTP_200_OK)
        self.assertEqual(cloned_response.status_code, status.HTTP_200_OK)

        source_files = {}
        for file in source_response.json():
            source_files[file["name"]] = file["sha256"]

        cloned_files = {}
        for file in cloned_response.json():
            cloned_files[file["name"]] = file["sha256"]

        self.assertGreater(len(source_files), 0)
        self.assertEqual(set(source_files.keys()), set(cloned_files.keys()))

        for name in source_files:
            # The QGIS project file is re-saved during clone configuration
            if name == self.p1.the_qgis_file_name:
                continue

            self.assertEqual(source_files[name], cloned_files[name])

        # compare QGIS file name
        self.assertEqual(cloned_project.the_qgis_file_name, self.p1.the_qgis_file_name)

        self.assertIsNotNone(cloned_project.qgis_project)
        self.assertEqual(
            set(
                cloned_project.qgis_project.layers.values_list(
                    "qgis_layer_id", flat=True
                )
            ),
            set(self.p1.qgis_project.layers.values_list("qgis_layer_id", flat=True)),
        )

    def test_process_projectfile_job_sets_the_qgis_version(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.t1.key)

        self.assertIsNone(self.p1.qgis_version)

        # Push the QGIS project file
        response = self._upload_file(
            self.u1,
            self.p1,
            "project.qgs",
            io.FileIO(testdata_path("self_contained.qgs"), "rb"),
        )

        self.p1.refresh_from_db()

        self.assertEqual(self.p1.qgis_version, "3.44.7")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.p1.qgis_version = None
        self.p1.save(update_fields=["qgis_version"])

        job = ProcessProjectfileJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.p1,
            created_by=self.u1,
        )

        wait_for_project_ok_status(self.p1)

        self.p1.refresh_from_db()
        job.refresh_from_db()

        self.assertEqual(
            job.feedback["outputs"]["project_details"]["project_details"][
                "qgis_version"
            ],
            "3.44.7",
        )
        self.assertEqual(self.p1.qgis_version, "3.44.7")

    def test_queue_job_single_project_person_owner_no_triggered_by(self):
        jobs = queue_job(self.p1, ProcessProjectfileJob)

        self.assertEqual(len(jobs), 1)

        job = jobs[0]

        self.assertEqual(job.created_by_id, self.u1.id)
        self.assertEqual(job.triggered_by_id, self.u1.id)
        self.assertEqual(job.project_id, self.p1.id)

    def test_queue_job_single_project_with_explicit_triggered_by(self):
        u2 = Person.objects.create_user(username="u2", password="abc123")
        jobs = queue_job(self.p1, ProcessProjectfileJob, triggered_by=u2)

        self.assertEqual(len(jobs), 1)

        job = jobs[0]

        self.assertEqual(job.created_by_id, u2.id)
        self.assertEqual(job.triggered_by_id, u2.id)

    def test_queue_job_multiple_projects_as_list(self):
        p2 = Project.objects.create(name="p2", is_public=False, owner=self.u1)

        jobs = queue_job([self.p1, p2], ProcessProjectfileJob)

        self.assertEqual(len(jobs), 2)

        for job in jobs:
            self.assertIn(job.project_id, [self.p1.id, p2.id])
            self.assertEqual(job.created_by_id, self.u1.id)
            self.assertEqual(job.triggered_by_id, self.u1.id)

    def test_queue_job_multiple_projects_as_queryset(self):
        p2 = Project.objects.create(name="p2", is_public=False, owner=self.u1)
        project_qs = Project.objects.filter(owner=self.u1)

        jobs = queue_job(project_qs, ProcessProjectfileJob)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(jobs), project_qs.count())

        for job in jobs:
            self.assertIn(job.project_id, [self.p1.id, p2.id])
            self.assertEqual(job.created_by_id, self.u1.id)
            self.assertEqual(job.triggered_by_id, self.u1.id)

    def test_queue_job_organization_owner_no_triggered_by(self):
        org_owner = Person.objects.create_user(username="org_owner", password="abc123")
        org = Organization.objects.create(username="org1", organization_owner=org_owner)
        project_org = Project.objects.create(
            name="org_project", is_public=False, owner=org
        )

        jobs = queue_job(project_org, ProcessProjectfileJob)

        self.assertEqual(len(jobs), 1)

        job = jobs[0]

        self.assertEqual(job.created_by_id, org_owner.id)
        self.assertEqual(job.triggered_by_id, org_owner.id)

    def test_queue_job_organization_owner_with_explicit_triggered_by(self):
        org_owner = Person.objects.create_user(username="org_owner", password="abc123")
        org = Organization.objects.create(username="org1", organization_owner=org_owner)
        project_org = Project.objects.create(
            name="org_project", is_public=False, owner=org
        )

        jobs = queue_job(project_org, ProcessProjectfileJob, triggered_by=self.u1)

        self.assertEqual(len(jobs), 1)

        job = jobs[0]

        self.assertNotEqual(job.created_by_id, org_owner.id)
        self.assertEqual(job.created_by_id, self.u1.id)
        self.assertNotEqual(job.triggered_by_id, org_owner.id)
        self.assertEqual(job.triggered_by_id, self.u1.id)

    def test_queue_job_invalid_job_model_raises(self):
        with self.assertRaises(AssertionError):
            queue_job(self.p1, PackageJob)

    def test_queue_job_processed_by_worker(self):
        self._upload_files(
            self.u1,
            self.p1,
            files=[("project.qgs", "delta/project_with_virtual.qgs")],
        )
        wait_for_project_ok_status(self.p1)

        jobs = queue_job(self.p1, ProcessProjectfileJob)

        self.assertEqual(len(jobs), 1)

        job = jobs[0]

        wait_for_project_ok_status(self.p1)

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FINISHED)

    def test_queue_job_queryset_all_jobs_complete(self):
        p2 = Project.objects.create(name="p2", is_public=False, owner=self.u1)

        for project in [self.p1, p2]:
            self._upload_files(
                self.u1,
                project,
                files=[("project.qgs", "delta/project_with_virtual.qgs")],
            )
            wait_for_project_ok_status(project)

        project_qs = Project.objects.filter(owner=self.u1)
        jobs = queue_job(project_qs, ProcessProjectfileJob)

        self.assertEqual(len(jobs), 2)

        for project in [self.p1, p2]:
            wait_for_project_ok_status(project)

        for job in jobs:
            job.refresh_from_db()

            self.assertEqual(job.status, Job.Status.FINISHED)
