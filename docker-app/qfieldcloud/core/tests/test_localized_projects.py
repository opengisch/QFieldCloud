import io
import logging

from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    SHARED_DATASETS_PROJECT_NAME,
    Job,
    Person,
    Project,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.filestorage.models import File

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="testuser", password="abc123")
        self.token = AuthToken.objects.get_or_create(user=self.user1)[0]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        self.user2 = Person.objects.create_user(username="testuser2", password="abc123")

        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        self.shared_datasets_project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME,
            is_public=False,
            owner=self.user1,
            file_storage="default",
        )

        self.shared_datasets_project.refresh_from_db()

    def get_localized_filenames_by_project_details(self, project: Project) -> list:
        filenames = []
        for layer in project.project_details["layers_by_id"].values():
            if layer["is_localized"]:
                # Extract the filename from the localized layer
                filename = layer["filename"].split("localized:")[-1]
                filenames.append(filename)

        return filenames

    def get_filenames_from_missing_localized_layers(self):
        missing_localized_layers = self.project1.get_missing_localized_layers()
        filenames = [
            layer["datasource"].split("|")[0].split(":")[-1]
            for layer in missing_localized_layers
        ]
        return filenames

    def test_shared_datasets_project_id(self):
        """
        Verifies that the localized dataset project ID is correctly returned
        as part of the main project's API metadata.
        """
        data = self.client.get(f"/api/v1/projects/{self.project1.id}/").json()
        self.assertEqual(
            data.get("shared_datasets_project_id"),
            str(self.shared_datasets_project.id),
        )

    def test_localized_datasets_property(self):
        """
        Uploads a QGIS project with references to localized layers,
        and checks that two such layers are detected in the project metadata.
        """
        resp = self._upload_file(
            self.user1,
            self.project1,
            "simple_bumblebees_wrong_localized.qgs",
            io.FileIO(testdata_path("simple_bumblebees_wrong_localized.qgs"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        processprojectfile_job = Job.objects.filter(
            project=self.project1, type=Job.Type.PROCESS_PROJECTFILE
        ).latest("updated_at")

        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        localized_layers = [layer for layer in self.project1.localized_layers]

        self.assertEqual(len(localized_layers), 2)

    def test_localized_layers_and_missing_localized_layers(self):
        """
        Tests the detection of available and missing localized layers:
        - Uploads one localized file and a QGIS project referencing two
        - Verifies which layers are marked as missing
        - Uploads the second file and confirms only one remains missing
        """
        resp = self._upload_file(
            self.user1,
            self.shared_datasets_project,
            "delta/polygons.geojson",
            io.FileIO(testdata_path("delta/polygons.geojson"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        resp = self._upload_file(
            self.user1,
            self.project1,
            "simple_bumblebees_wrong_localized.qgs",
            io.FileIO(testdata_path("simple_bumblebees_wrong_localized.qgs"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        processprojectfile_job = Job.objects.filter(
            project=self.project1, type=Job.Type.PROCESS_PROJECTFILE
        ).latest("updated_at")

        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        # Localized layers found in the localized datasets project
        available_localized_filenames = set(
            File.objects.filter(
                project_id=self.shared_datasets_project.id,
            ).values_list("name", flat=True)
        )

        self.assertEqual(len(available_localized_filenames), 1)

        # Localized layers found in the project1 project
        project_localized_filenames = self.get_localized_filenames_by_project_details(
            self.project1
        )

        missing_localized_layers_filenames = (
            self.get_filenames_from_missing_localized_layers()
        )

        self.assertNotIn("delta/polygons.geojson", project_localized_filenames)

        self.assertEqual(len(missing_localized_layers_filenames), 2)

        self.assertListEqual(
            missing_localized_layers_filenames,
            ["bumblebees.gpkg", "bumblebees_doesnotexist.gpkg"],
        )

        # Upload the missing bumblebees.gpkg file
        resp = self._upload_file(
            self.user1,
            self.shared_datasets_project,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        missing_localized_layers_filenames = (
            self.get_filenames_from_missing_localized_layers()
        )

        self.assertEqual(len(missing_localized_layers_filenames), 1)

    def test_no_missing_localized_layers(self):
        """
        Ensures that when all localized layers referenced in the QGIS project
        are available in the localized datasets project, the list of missing
        localized layers is empty.
        """
        resp = self._upload_file(
            self.user1,
            self.shared_datasets_project,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        project = Project.objects.create(
            name="projectX", is_public=False, owner=self.user1
        )

        resp = self._upload_file(
            self.user1,
            project,
            "simple_bumblebees_correct_localized.qgs",
            io.FileIO(testdata_path("simple_bumblebees_correct_localized.qgs"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(project)
        project.refresh_from_db()

        processprojectfile_job = Job.objects.filter(
            project=project, type=Job.Type.PROCESS_PROJECTFILE
        ).latest("updated_at")

        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        self.assertListEqual(project.get_missing_localized_layers(), [])

    def test_get_missing_localized_layers_without_localized_project(self):
        """
        Verifies that when no localized datasets project is configured,
        all localized layers are reported as missing.
        """
        token = AuthToken.objects.get_or_create(user=self.user2)[0]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token.key)

        project2 = Project.objects.create(
            name="project2", is_public=False, owner=self.user2
        )

        resp = self._upload_file(
            self.user2,
            project2,
            "simple_bumblebees_wrong_localized.qgs",
            io.FileIO(testdata_path("simple_bumblebees_wrong_localized.qgs"), "rb"),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        wait_for_project_ok_status(project2)
        project2.refresh_from_db()

        processprojectfile_job = Job.objects.filter(
            project=project2, type=Job.Type.PROCESS_PROJECTFILE
        ).latest("updated_at")

        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)

        localized_layers = self.get_localized_filenames_by_project_details(project2)

        missing_localized_layers = project2.get_missing_localized_layers()

        self.assertEqual(len(missing_localized_layers), len(localized_layers))
