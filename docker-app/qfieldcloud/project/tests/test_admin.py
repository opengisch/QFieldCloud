import logging

from django.test import TransactionTestCase
from django.urls import reverse

from qfieldcloud.core.models import Job, Person, ProcessProjectfileJob
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(TransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.project = Project.objects.create(owner=self.user1, name="project1")

    def test_project_admin_run_process_projectfile_job_queues_job_and_redirects(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse(
                "admin:project_project_run_process_projectfile_job",
                args=[self.project.pk],
            )
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            reverse("admin:project_project_change", args=[self.project.pk]),
        )
        self.assertEqual(
            list(
                ProcessProjectfileJob.objects.filter(project=self.project).values_list(
                    "status", "triggered_by"
                )
            ),
            [(Job.Status.PENDING, self.user1.pk)],
        )

    def test_project_admin_change_view_renders_files_widget(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse("admin:project_project_change", args=[self.project.pk])
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="qfc-admin-project-files-load-wrapper"')
        # the widget's script finds its buttons by these classes
        self.assertContains(resp, "qfc-admin-projects-files-actions-reload-btn")
        self.assertContains(resp, "qfc-admin-projects-files-actions-info-btn")
        self.assertContains(resp, "qfc-admin-projects-files-actions-download-btn")
        self.assertContains(resp, "qfc-admin-projects-files-actions-delete-btn")

    def test_project_admin_change_view_shows_actions_and_related_links(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse("admin:project_project_change", args=[self.project.pk])
        )

        with self.subTest("Test the change view links to the process projectfile job"):
            self.assertContains(
                resp,
                f'href="{reverse("admin:project_project_run_process_projectfile_job", args=[self.project.pk])}"',
            )

        jobs_action_url = reverse(
            "admin:project_project_related_jobs", args=[self.project.pk]
        )
        faulty_deltafiles_action_url = reverse(
            "admin:project_project_related_faulty_deltafiles", args=[self.project.pk]
        )

        with self.subTest(
            "Test the change view links to the project's jobs and faulty deltafiles"
        ):
            self.assertContains(resp, f'href="{jobs_action_url}"')
            self.assertContains(resp, f'href="{faulty_deltafiles_action_url}"')

        with self.subTest(
            "Test the related actions redirect to the changelists filtered by the project"
        ):
            jobs_resp = self.client.get(jobs_action_url)
            faulty_deltafiles_resp = self.client.get(faulty_deltafiles_action_url)

            self.assertEqual(
                jobs_resp.url,
                f"{reverse('admin:core_job_changelist')}?q={self.project.pk}",
            )
            self.assertEqual(
                faulty_deltafiles_resp.url,
                f"{reverse('admin:core_faultydeltafile_changelist')}?q={self.project.pk}",
            )
