import logging
from unittest import mock

from django.core.files.base import ContentFile
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    ApplyJob,
    Job,
    PackageJob,
    Person,
    ProcessProjectfileJob,
    Project,
)
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.subscription.exceptions import (
    InactiveSubscriptionError,
    PlanInsufficientError,
    QuotaError,
)
from qfieldcloud.subscription.models import Subscription

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]
        set_subscription(self.user1, "default_user")

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", owner=self.user1, description="desc", is_public=False
        )
        self.job = Job.objects.create(
            type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
        )
        self.package_job = PackageJob.objects.create(
            type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
        )
        self.processprojectfile_job = ProcessProjectfileJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.project1,
            created_by=self.user1,
        )
        self.delta_apply_job = ApplyJob.objects.create(
            type=Job.Type.DELTA_APPLY,
            project=self.project1,
            created_by=self.user1,
            overwrite_conflicts=True,
        )

    def test_create_job_succesfully(self):
        # Test can create all types of jobs successfully
        job = PackageJob.objects.create(
            type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
        )
        self.assertEqual(job.status, Job.Status.PENDING)

        self.assertEqual(self.package_job.status, Job.Status.PENDING)

        processprojectfile_job = ProcessProjectfileJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.project1,
            created_by=self.user1,
        )
        self.assertEqual(processprojectfile_job.status, Job.Status.PENDING)

        deltaapply_job = ApplyJob.objects.create(
            type=Job.Type.DELTA_APPLY,
            project=self.project1,
            created_by=self.user1,
            overwrite_conflicts=True,
        )
        self.assertEqual(deltaapply_job.status, Job.Status.PENDING)

    def test_create_job_by_inactive_project_owner(self):
        subscription = self.project1.owner.useraccount.current_subscription
        subscription.status = Subscription.Status.INACTIVE_DRAFT
        subscription.save()

        # Make sure the user is inactive
        self.assertFalse(self.project1.owner.useraccount.current_subscription.is_active)

        self.check_cannot_create_jobs(InactiveSubscriptionError)
        self.check_can_update_existing_jobs()

    def test_create_job_if_project_owner_is_over_quota(self):
        plan = self.user1.useraccount.current_subscription.plan
        more_bytes_than_plan = (plan.storage_mb * 1000 * 1000) + 1

        # TODO Delete with QF-4963 Drop support for legacy storage
        if self.project1.uses_legacy_storage:
            # Create a project that uses all the storage
            self.project1.file_storage_bytes = more_bytes_than_plan
            self.project1.save()
        else:
            FileVersion.objects.add_version(
                project=self.project1,
                filename="bigfile.name",
                content=ContentFile(b"x" * more_bytes_than_plan, "dummy.name"),
                file_type=File.FileType.PROJECT_FILE,
                uploaded_by=self.user1,
            )

        self.check_cannot_create_jobs(QuotaError)
        self.check_can_update_existing_jobs()

    def test_create_job_on_project_with_online_vector_data_for_unsufficient_owner(
        self,
    ):
        # The actual property is tested in qfieldcloud.core.tests.test_packages.QfcTestCase.test_has_no_online_vector_data
        with mock.patch.object(
            Project, "has_online_vector_data", new_callable=mock.PropertyMock
        ) as mock_has_online_vector_data:
            mock_has_online_vector_data.return_value = True
            self.assertTrue(self.project1.has_online_vector_data)

            # Make sure the user's plan does not allow online vector data
            self.assertFalse(
                self.project1.owner.useraccount.current_subscription.plan.is_external_db_supported
            )

            with self.assertRaises(PlanInsufficientError):
                PackageJob.objects.create(
                    type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
                )

            with self.assertRaises(PlanInsufficientError):
                ApplyJob.objects.create(
                    type=Job.Type.DELTA_APPLY,
                    project=self.project1,
                    created_by=self.user1,
                    overwrite_conflicts=True,
                )

            # Can still create processprojectfile job
            processprojectfile_job = ProcessProjectfileJob.objects.create(
                type=Job.Type.PROCESS_PROJECTFILE,
                project=self.project1,
                created_by=self.user1,
            )
            self.assertEqual(processprojectfile_job.status, Job.Status.PENDING)

            self.check_can_update_existing_jobs()

    def check_cannot_create_jobs(self, error):
        # Can still create processprojectfile job
        ProcessProjectfileJob.objects.create(
            type=Job.Type.PROCESS_PROJECTFILE,
            project=self.project1,
            created_by=self.user1,
        )

        with self.assertRaises(error):
            PackageJob.objects.create(
                type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
            )

        with self.assertRaises(error):
            ApplyJob.objects.create(
                type=Job.Type.DELTA_APPLY,
                project=self.project1,
                created_by=self.user1,
                overwrite_conflicts=True,
            )

    def check_can_update_existing_jobs(self):
        # Can update existing jobs
        self.job.status = Job.Status.FAILED
        self.job.save()

        self.package_job.status = Job.Status.FAILED
        self.package_job.save()

        self.processprojectfile_job.status = Job.Status.FAILED
        self.processprojectfile_job.save()

        self.delta_apply_job.status = Job.Status.FAILED
        self.delta_apply_job.save()
