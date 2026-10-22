import logging

from django.test import TransactionTestCase
from django.urls import reverse

from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    Job,
    Person,
    ProcessProjectfileJob,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(TransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        # staff user without any model permissions
        self.staff_user = Person.objects.create_user(
            username="staff", password="secret", is_staff=True
        )
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.project = Project.objects.create(name="project1", owner=self.user1)

        self.delta_content = {
            "uuid": "f85b4d28-2444-40ce-95a8-6502bf4f00d9",
            "method": "create",
        }
        self.delta = Delta.objects.create(
            deltafile_id="f85b4d28-2444-40ce-95a8-6502bf4f00d9",
            project=self.project,
            client_id="f85b4d28-2444-40ce-95a8-6502bf4f00d9",
            created_by=self.user1,
            content=self.delta_content,
        )

        self.apply_job = ApplyJob.objects.create(
            project=self.project,
            created_by=self.user1,
            overwrite_conflicts=False,
        )
        ApplyJobDelta.objects.create(apply_job=self.apply_job, delta=self.delta)

        self.failed_job = ProcessProjectfileJob.objects.create(
            project=self.project,
            created_by=self.user1,
            status=Job.Status.FAILED,
        )
        self.other_failed_job = ProcessProjectfileJob.objects.create(
            project=self.project,
            created_by=self.user1,
            status=Job.Status.FAILED,
        )

    def test_job_admin_change_view_links_to_job_actions(self):
        self.client.force_login(self.superuser)

        with self.subTest(
            "Test the apply job change view links to the deltafile export and re-run"
        ):
            resp = self.client.get(
                reverse("admin:core_job_change", args=[self.apply_job.pk])
            )

            self.assertEqual(resp.status_code, 200)
            self.assertContains(
                resp,
                f'href="{reverse("admin:core_job_export_applyjob_deltafile", args=[self.apply_job.pk])}"',
            )
            self.assertContains(
                resp,
                f'href="{reverse("admin:core_job_rerun_job", args=[self.apply_job.pk])}"',
            )

        with self.subTest(
            "Test a non-apply job change view links to re-run but not the deltafile export"
        ):
            resp = self.client.get(
                reverse("admin:core_job_change", args=[self.failed_job.pk])
            )

            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, "export-deltafile")
            self.assertContains(
                resp,
                f'href="{reverse("admin:core_job_rerun_job", args=[self.failed_job.pk])}"',
            )

    def test_job_admin_export_applyjob_deltafile_returns_json_attachment(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse(
                "admin:core_job_export_applyjob_deltafile", args=[self.apply_job.pk]
            )
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertEqual(
            resp["Content-Disposition"],
            f"attachment; filename=applyjob_deltas_{self.project.pk}.json",
        )
        self.assertEqual(
            resp.json(),
            {
                "deltas": [self.delta_content],
                "files": [],
                "id": "11111111-1111-1111-1111-111111111111",
                "project": str(self.project.pk),
                "version": "1.0",
            },
        )
