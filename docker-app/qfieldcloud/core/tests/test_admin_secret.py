import logging

from django.test import TestCase
from django.urls import reverse

from qfieldcloud.core.models import Organization, Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


# TODO
class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.organization = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        self.project = Project.objects.create(name="project1", owner=self.user1)

        self.secret_add_url = reverse("admin:core_secret_add")

        self.client.force_login(self.superuser)

    def test_add_secret_action_links_to_secret_add_view_for_the_parent(self):
        organization_action_url = reverse(
            "admin:core_organization_add_secret", args=[self.organization.pk]
        )
        project_action_url = reverse(
            "admin:project_project_add_secret", args=[self.project.pk]
        )

        with self.subTest(
            "Test the organization change view shows the add secret action"
        ):
            resp = self.client.get(
                reverse("admin:core_organization_change", args=[self.organization.pk])
            )

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'href="{organization_action_url}"')

        with self.subTest(
            "Test the organization action redirects to adding a secret for the organization"
        ):
            resp = self.client.get(organization_action_url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(
                resp.url,
                f"{self.secret_add_url}?organization_id={self.organization.pk}",
            )

        with self.subTest("Test the project change view shows the add secret action"):
            resp = self.client.get(
                reverse("admin:project_project_change", args=[self.project.pk])
            )

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'href="{project_action_url}"')

        with self.subTest(
            "Test the project action redirects to adding a secret for the project"
        ):
            resp = self.client.get(project_action_url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(
                resp.url, f"{self.secret_add_url}?project_id={self.project.pk}"
            )

    def test_add_secret_action_requires_add_secret_permission(self):
        staff_user = Person.objects.create_user(
            username="staff", password="secret", is_staff=True
        )
        self.client.force_login(staff_user)

        resp = self.client.get(
            reverse("admin:core_organization_add_secret", args=[self.organization.pk])
        )

        self.assertEqual(resp.status_code, 403)

    def test_secret_admin_add_view_prefills_parent_from_query_params(self):
        with self.subTest("Test the add view prefills the organization"):
            resp = self.client.get(
                self.secret_add_url, {"organization_id": self.organization.pk}
            )

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.context["adminform"].form.initial["organization"],
                self.organization,
            )
            self.assertIsNone(resp.context["adminform"].form.initial["project"])

        with self.subTest("Test the add view prefills the project"):
            resp = self.client.get(self.secret_add_url, {"project_id": self.project.pk})

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.context["adminform"].form.initial["project"], self.project
            )
            self.assertIsNone(resp.context["adminform"].form.initial["organization"])
