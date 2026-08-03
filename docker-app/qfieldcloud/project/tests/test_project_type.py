import io
import logging

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans, testdata_path
from qfieldcloud.core.utils2 import jobs
from qfieldcloud.project.models import SHARED_DATASETS_PROJECT_NAME, Project

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

    def test_project_type_defaults_to_regular(self):
        """Test that a normally named project gets a project type of `REGULAR`"""
        project = Project.objects.create(name="project", owner=self.user1)

        self.assertEqual(project.project_type, Project.ProjectType.REGULAR)

    def test_project_type_set_to_shared_datasets_on_create(self):
        """Test that creating a project named as the constant `SHARED_DATASETS_PROJECT_NAME` sets project type of `SHARED_DATASETS`."""
        project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
        )

        self.assertEqual(project.project_type, Project.ProjectType.SHARED_DATASETS)

    def test_project_type_updates_when_renamed_to_shared_datasets(self):
        """Test that renaming an existing empty project (no QGIS project file) as the constant `SHARED_DATASETS_PROJECT_NAME` flips `project_type`"""
        project = Project.objects.create(name="project", owner=self.user1)
        self.assertEqual(project.project_type, Project.ProjectType.REGULAR)

        project.name = SHARED_DATASETS_PROJECT_NAME
        project.save()
        project.refresh_from_db()

        self.assertEqual(project.project_type, Project.ProjectType.SHARED_DATASETS)

    def test_project_type_cannot_be_renamed_away_from_shared_datasets(self):
        """Test that renaming the `shared_datasets` project away raises, since its `project_type` cannot be changed."""
        project = Project.objects.create(
            name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
        )

        project.name = "no_longer_shared"

        with self.assertRaises(ValidationError):
            project.save()

        project.refresh_from_db()
        self.assertEqual(project.name, SHARED_DATASETS_PROJECT_NAME)
        self.assertEqual(project.project_type, Project.ProjectType.SHARED_DATASETS)

    def test_project_type_can_be_set_to_template_on_create(self):
        """Test that a normally named project can be created as of type `TEMPLATE`."""
        project = Project.objects.create(
            name="project",
            owner=self.user1,
            project_type=Project.ProjectType.TEMPLATE,
        )

        self.assertEqual(project.project_type, Project.ProjectType.TEMPLATE)

    def test_project_type_cannot_be_forced_to_shared_datasets(self):
        """Test that a normally named project raises when saved as of type `SHARED_DATASETS`"""
        with self.assertRaises(ValidationError):
            Project.objects.create(
                name="project",
                owner=self.user1,
                project_type=Project.ProjectType.SHARED_DATASETS,
            )

        self.assertFalse(Project.objects.filter(name="project").exists())

    def test_api_can_set_project_type_to_template(self):
        """Test that the API allows creating a project with `project_type=TEMPLATE`."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/projects/",
            {
                "name": "api_created_template",
                "owner": "user1",
                "project_type": Project.ProjectType.TEMPLATE.value,
            },
        )
        self.assertTrue(status.is_success(response.status_code))

        project = Project.objects.get(name="api_created_template")

        self.assertEqual(project.project_type, Project.ProjectType.TEMPLATE)

    def test_api_cannot_set_project_type_to_shared_datasets(self):
        """Test that the API rejects creating a project with `project_type=SHARED_DATASETS`."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post(
            "/api/v1/projects/",
            {
                "name": "api_created_project",
                "owner": "user1",
                "project_type": Project.ProjectType.SHARED_DATASETS.value,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "api_error")

        self.assertFalse(Project.objects.filter(name="api_created_project").exists())

    def test_api_rejects_invalid_project_type_values(self):
        """Test that the API rejects `project_type` values that don't exactly match an acceptable string."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        with self.subTest("Nonexistent project type value is rejected"):
            response = self.client.post(
                "/api/v1/projects/",
                {
                    "name": "api_project_nonexistent_type",
                    "owner": "user1",
                    "project_type": "nonexistent",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["code"], "api_error")
            self.assertFalse(
                Project.objects.filter(name="api_project_nonexistent_type").exists()
            )

        with self.subTest("Wrong casing of an otherwise valid value is rejected"):
            response = self.client.post(
                "/api/v1/projects/",
                {
                    "name": "api_project_wrong_casing",
                    "owner": "user1",
                    "project_type": Project.ProjectType.TEMPLATE.label,
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["code"], "api_error")
            self.assertFalse(
                Project.objects.filter(name="api_project_wrong_casing").exists()
            )

    def test_api_change_project_type(self):
        """Test API behavior when changing `project_type` for various project/target combinations."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        with self.subTest(
            "Project of type `REGULAR` can be changed to type `TEMPLATE`"
        ):
            project = Project.objects.create(name="project_regular", owner=self.user1)

            response = self.client.patch(
                f"/api/v1/projects/{project.id}/",
                {"project_type": Project.ProjectType.TEMPLATE.value},
            )
            self.assertTrue(status.is_success(response.status_code))

            project.refresh_from_db()
            self.assertEqual(project.project_type, Project.ProjectType.TEMPLATE)

        with self.subTest(
            "Project of type `REGULAR` cannot be changed to type `SHARED_DATASETS`"
        ):
            project = Project.objects.create(
                name="project_shared_datasets_attempt", owner=self.user1
            )

            response = self.client.patch(
                f"/api/v1/projects/{project.id}/",
                {"project_type": Project.ProjectType.SHARED_DATASETS.value},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["code"], "api_error")

            project.refresh_from_db()
            self.assertEqual(project.project_type, Project.ProjectType.REGULAR)

        with self.subTest(
            "Project of type `SHARED_DATASETS` cannot be changed to another type"
        ):
            project = Project.objects.create(
                name=SHARED_DATASETS_PROJECT_NAME, owner=self.user1
            )

            response = self.client.patch(
                f"/api/v1/projects/{project.id}/",
                {"project_type": Project.ProjectType.TEMPLATE.value},
            )
            self.assertTrue(status.is_success(response.status_code))

            project.refresh_from_db()
            self.assertEqual(project.project_type, Project.ProjectType.SHARED_DATASETS)

    def test_repackage_not_allowed_on_template_project(self):
        """Test that repackaging a template project raises `OperationNotAllowedForTemplateProjectError`."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        project = Project.objects.create(
            name="template_project",
            owner=self.user1,
            project_type=Project.ProjectType.TEMPLATE,
        )

        # Upload a QGIS project file, so the "no QGIS file" check does not
        # shadow the template check.
        response = self.client.post(
            f"/api/v1/files/{project.id}/simple_bumblebees.qgs/",
            {"file": io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb")},
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))

        project.refresh_from_db()
        self.assertTrue(project.has_the_qgis_file)

        with self.assertRaises(exceptions.OperationNotAllowedForTemplateProjectError):
            jobs.repackage(project, self.user1)

    def test_apply_deltas_not_allowed_on_template_project(self):
        """Test that applying deltas on a template project raises `OperationNotAllowedForTemplateProjectError`."""
        project = Project.objects.create(
            name="template_project",
            owner=self.user1,
            project_type=Project.ProjectType.TEMPLATE,
        )

        with self.assertRaises(exceptions.OperationNotAllowedForTemplateProjectError):
            jobs.apply_deltas(
                project,
                self.user1,
                project_file="simple_bumblebees.qgs",
                overwrite_conflicts=False,
            )
