import logging
from io import StringIO

from django.conf import settings
from django.urls import reverse
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.models import Job, Person, ProcessProjectfileJob
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.project = Project.objects.create(
            owner=self.user1,
            name="project1",
            file_storage="default",
        )

    def test_project_admin_run_process_projectfile_job_queues_job_and_redirects(self):
        url = reverse(
            "admin:project_project_run_process_projectfile_job", args=[self.project.pk]
        )

        with self.subTest("Test the view redirects an anonymous user to login"):
            resp = self.client.get(url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.url, f"{reverse('admin:login')}?next={url}")
            self.assertEqual(
                ProcessProjectfileJob.objects.filter(project=self.project).count(), 0
            )

        with self.subTest(
            "Test the view queues a pending process projectfile job and redirects to the project"
        ):
            self.client.force_login(self.superuser)

            resp = self.client.get(url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(
                resp.url,
                reverse("admin:project_project_change", args=[self.project.pk]),
            )
            self.assertEqual(
                list(
                    ProcessProjectfileJob.objects.filter(
                        project=self.project
                    ).values_list("status", "triggered_by")
                ),
                [(Job.Status.PENDING, self.user1.pk)],
            )

    def test_project_admin_files_widget_api_lists_project_files(self):
        self._upload_file(self.user1, self.project, "file.txt", StringIO("Hello"))
        # drop the API token set by the upload, so the requests below use the session login
        self.client.credentials()

        files_api_url = f"/{settings.QFIELDCLOUD_ADMIN_URI}api/files/{self.project.pk}/"

        with self.subTest("Test the change view renders the files widget"):
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

        with self.subTest(
            "Test the change view links to the project's jobs and faulty deltafiles"
        ):
            self.assertContains(
                resp,
                f'href="{reverse("admin:core_job_changelist")}?q={self.project.pk}"',
            )
            self.assertContains(
                resp,
                f'href="{reverse("admin:core_faultydeltafile_changelist")}?q={self.project.pk}"',
            )
