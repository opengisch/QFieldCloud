import io

from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Secret,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.core.utils2.jobs import repackage
from qfieldcloud.filestorage.models import File


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.u1 = Person.objects.create(username="u1", password="u1")
        self.u2 = Person.objects.create(username="u2", password="u2")

        self.o1 = Organization.objects.create(username="o1", organization_owner=self.u1)

        # Activate Subscriptions
        set_subscription(self.o1, "default_org")

        self.p1 = Project.objects.create(name="p1", owner=self.o1)

        members = [
            OrganizationMember(
                organization=self.o1,
                member=self.u2,
                role=OrganizationMember.Roles.ADMIN,
            ),
        ]

        self.o1.members.bulk_create(members)

        collaborators = [
            ProjectCollaborator(
                project=self.p1,
                collaborator=self.u2,
                role=ProjectCollaborator.Roles.ADMIN,
            ),
        ]

        self.p1.direct_collaborators.bulk_create(collaborators)

    def _create_secret(self, **kwargs) -> Secret:
        return Secret.objects.create(
            type=Secret.Type.ENVVAR,
            **kwargs,
        )

    def test_create_user_level_packages(self):
        # upload data & QGIS project files to the project.
        self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self._upload_file(
            self.u1,
            self.p1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        # create secrets for project and assigned to users
        self._create_secret(name="SECRET", project=self.p1, value="p1")
        self._create_secret(
            name="SECRET", project=self.p1, assigned_to=self.u1, value="u1"
        )
        self._create_secret(
            name="SECRET", project=self.p1, assigned_to=self.u2, value="u2"
        )

        self.p1.refresh_from_db()

        # create a package for the two users
        u1_package_job = repackage(self.p1, self.u1)
        u2_package_job = repackage(self.p1, self.u2)

        # there must be two separate package jobs per user
        self.assertNotEqual(u1_package_job, u2_package_job)

        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        latest_package_jobs_qs = self.p1.latest_package_jobs()

        self.assertEquals(latest_package_jobs_qs.count(), 2)

        u1_latest_package_job = latest_package_jobs_qs.get(triggered_by=self.u1)
        u2_latest_package_job = latest_package_jobs_qs.get(triggered_by=self.u2)

        self.assertEquals(u1_package_job.id, u1_latest_package_job.id)
        self.assertEquals(u2_package_job.id, u2_latest_package_job.id)

    def test_create_org_level_packages(self):
        # upload data & QGIS project files to the project.
        self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self._upload_file(
            self.u1,
            self.p1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        # create secrets for organization and assigned to user u1
        self._create_secret(name="SECRET", organization=self.o1, value="o1")
        self._create_secret(
            name="SECRET", organization=self.o1, assigned_to=self.u1, value="u1"
        )

        self.p1.refresh_from_db()

        # create a package for user u1
        u1_package_job = repackage(self.p1, self.u1)

        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        latest_package_jobs_qs = self.p1.latest_package_jobs()

        self.assertEquals(latest_package_jobs_qs.first(), u1_package_job)
        self.assertEquals(latest_package_jobs_qs.count(), 1)

        # create a package for user u2
        u2_package_job = repackage(self.p1, self.u2)

        latest_package_jobs_qs = self.p1.latest_package_jobs()

        self.assertNotEqual(u1_package_job, u2_package_job)
        self.assertEquals(latest_package_jobs_qs.count(), 2)
        self.assertEquals(latest_package_jobs_qs.last(), u2_package_job)

    def test_create_secrets_and_packages(self):
        # upload data & QGIS project files to the project.
        self._upload_file(
            self.u1,
            self.p1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self._upload_file(
            self.u1,
            self.p1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        # create a project-level secret
        self._create_secret(name="SECRET", project=self.p1, value="p1")

        self.p1.refresh_from_db()

        package_job_1 = repackage(self.p1, self.u1)
        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        latest_package_jobs_qs = self.p1.latest_package_jobs()

        self.assertIn(package_job_1, latest_package_jobs_qs)

        # create a user-level secret, assigned to user u1 for project p1
        self._create_secret(
            name="SECRET", assigned_to=self.u1, project=self.p1, value="u1"
        )

        package_job_2 = repackage(self.p1, self.u1)

        self.assertNotEqual(package_job_1, package_job_2)

        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        latest_package_jobs_qs = self.p1.latest_package_jobs()

        self.assertEquals(latest_package_jobs_qs.count(), 1)
        self.assertIn(package_job_2, latest_package_jobs_qs)
        self.assertNotIn(package_job_1, latest_package_jobs_qs)

        # check that files from 1st package are not there anymore
        package_job_1_files = File.objects.filter(
            package_job=package_job_1,
            file_type=File.FileType.PACKAGE_FILE,
        )

        self.assertEquals(package_job_1_files.count(), 0)
