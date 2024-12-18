import logging
import time
from unittest import mock

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    ApplyJob,
    Job,
    PackageJob,
    Person,
    ProcessProjectfileJob,
    Project,
)
from qfieldcloud.subscription.exceptions import (
    InactiveSubscriptionError,
    PlanInsufficientError,
    QuotaError,
)
from qfieldcloud.subscription.models import Subscription
from rest_framework import status
from rest_framework.test import APITestCase

from .utils import set_subscription, setup_subscription_plans, testdata_path, wait_for_project_ok_status

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

        # Create a project that uses all the storage
        more_bytes_than_plan = (plan.storage_mb * 1000 * 1000) + 1
        Project.objects.create(
            name="p1",
            owner=self.user1,
            file_storage_bytes=more_bytes_than_plan,
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

    def test_create_job_bad_layer_handler_extracted_values(self):
        # Test that BadLayerHandler is parsing data properly during package and process projectfile jobs
        
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        
        # project = Project.objects.create(
        #     name="simple_bumblebees_wrong_localized", owner=self.user1, description="desc", is_public=False
        # )

        # response = self.client.post(
        #     "/api/v1/jobs/",
        #     {
        #         "project_id": project.id,
        #         "type": Job.Type.PROCESS_PROJECTFILE.value,
        #     },
        # )
        # self.assertTrue(status.is_success(response.status_code))
        # job_id = response.json().get("id")
        
        # Push the QGIS project file
        file_path = testdata_path("simple_bumblebees_wrong_localized.qgs")
        response = self.client.post(
            f"/api/v1/files/{self.project1.id}/project.qgs/",
            {
                "file": open(file_path, "rb"),
            },
            format="multipart",
        )
        self.assertTrue(status.is_success(response.status_code))
        
        # processprojectfile_job = ProcessProjectfileJob.objects.create(
        #     type=Job.Type.PROCESS_PROJECTFILE,
        #     project=self.project1,
        #     created_by=self.user1,
        # )
        # self.assertEqual(processprojectfile_job.status, Job.Status.PENDING)
                
        print("--- BEFORE ---")
        for job in Job.objects.filter(type=Job.Type.PROCESS_PROJECTFILE):
            print(f"{job.project}, {job.type}, {job.status}")
    
        # Wait for the worker to do the job
        time.sleep(5)
        
        print("--- AFTER ---")
        for job in Job.objects.filter(type=Job.Type.PROCESS_PROJECTFILE):
            print(f"{job.project}, {job.type}, {job.status}")
        
        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()
        
        # processprojectfile_job = ProcessProjectfileJob.objects.get(id=job_id)
        processprojectfile_job = Job.objects.filter(type=Job.Type.PROCESS_PROJECTFILE).latest(
            "updated_at"
        )
        
        self.assertEqual(processprojectfile_job.status, Job.Status.FINISHED)
        self.assertIsNotNone(processprojectfile_job.feedback)
