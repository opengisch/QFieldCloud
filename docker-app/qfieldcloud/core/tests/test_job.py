import logging
from unittest import mock

from django.forms.models import ValidationError
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.exceptions import QuotaError
from qfieldcloud.core.models import Job, Person, Project
from qfieldcloud.subscription.models import Subscription
from rest_framework.test import APITestCase

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", owner=self.user1, description="desc", is_public=False
        )

    def test_create_job_succesfully(self):
        job = Job.objects.create(
            type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
        )

        self.assertEqual(job.status, Job.Status.PENDING)

    def test_create_job_by_inactive_user(self):
        subscription = self.user1.useraccount.active_subscription
        subscription.status = Subscription.Status.INACTIVE_DRAFT
        subscription.save()

        # Make sure the user is inactive
        self.assertFalse(subscription.is_active)

        # Cannot create job if user's subscription is inactive
        with self.assertRaises(ValidationError):
            Job.objects.create(
                type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
            )

    def test_create_job_if_user_is_over_quota(self):
        plan = self.user1.useraccount.active_subscription.plan

        # Create a project that uses all the storage
        more_bytes_than_plan = (plan.storage_mb * 1000 * 1000) + 1
        Project.objects.create(
            name="p1",
            owner=self.user1,
            file_storage_bytes=more_bytes_than_plan,
        )

        # Cannot create job if the user's plan is over quota
        with self.assertRaises(QuotaError):
            Job.objects.create(
                type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
            )

    def test_create_job_on_project_with_online_vector_data_for_unsupported_user_plan(
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
                self.user1.useraccount.active_subscription.plan.is_external_db_supported
            )

            # Cannot create job with a project that has online vector data
            with self.assertRaises(ValidationError):
                Job.objects.create(
                    type=Job.Type.PACKAGE, project=self.project1, created_by=self.user1
                )
