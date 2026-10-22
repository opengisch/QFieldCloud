import logging

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, TestCase
from django.urls import reverse

from qfieldcloud.core.admin import SecretAdmin, qfc_admin_site
from qfieldcloud.core.models import (
    Job,
    Organization,
    OrganizationMember,
    Person,
    ProcessProjectfileJob,
    ProjectCollaborator,
    Secret,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.enums import ProjectCollaboratorRole
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class MisconfiguredSecretAdmin(SecretAdmin):
    list_display_auto_fkey_fields = ("name",)


# TODO
class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        # `user10` must not match an exact `user1` search
        self.user10 = Person.objects.create_user(username="user10", password="abc123")
        self.user2 = Person.objects.create_user(username="user2", password="abc123")

        self.project1 = Project.objects.create(name="project1", owner=self.user1)
        self.project10 = Project.objects.create(name="project10", owner=self.user10)
        self.public_project = Project.objects.create(
            name="public_project", owner=self.user1, is_public=True
        )
        ProjectCollaborator.objects.create(
            collaborator=self.user2,
            project=self.project1,
            role=ProjectCollaboratorRole.EDITOR,
        )
        ProjectCollaborator.objects.create(
            collaborator=self.user2,
            project=self.public_project,
            role=ProjectCollaboratorRole.EDITOR,
        )

        self.organization1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        self.organization2 = Organization.objects.create(
            username="org2", organization_owner=self.user10
        )
        OrganizationMember.objects.create(
            organization=self.organization2, member=self.user2
        )

        self.request = RequestFactory().get("/")
        self.request.user = self.superuser

        self.client.force_login(self.superuser)

    def _search_projects(self, query: str) -> list[str]:
        resp = self.client.get(
            reverse("admin:project_project_changelist"), {"q": query}
        )

        return sorted(project.name for project in resp.context["cl"].queryset)

    def _search_organizations(self, query: str) -> list[str]:
        resp = self.client.get(
            reverse("admin:core_organization_changelist"), {"q": query}
        )

        return sorted(
            organization.username for organization in resp.context["cl"].queryset
        )

    def _get_job_changelist_ordering(self, params: dict[str, str]) -> list[str]:
        resp = self.client.get(reverse("admin:core_job_changelist"), params)
        changelist = resp.context["cl"]

        return changelist.get_ordering(resp.wsgi_request, changelist.root_queryset)

    def test_list_display_auto_fkey_fields_renders_foreign_keys_as_links(self):
        secret = Secret.objects.create(
            name="SECRET1",
            type=Secret.Type.ENVVAR,
            organization=self.organization1,
            created_by=self.user1,
            value="value",
        )
        secret_admin = qfc_admin_site._registry[Secret]
        list_display = secret_admin.get_list_display(self.request)

        with self.subTest("Test only the foreign key columns are replaced"):
            self.assertEqual(
                [column for column in list_display if isinstance(column, str)],
                ["name", "type", "created_at"],
            )
            self.assertEqual(
                [
                    column.admin_order_field
                    for column in list_display
                    if not isinstance(column, str)
                ],
                ["assigned_to", "project", "organization", "created_by"],
            )

        project_link, organization_link = list_display[3], list_display[4]

        with self.subTest("Test a set foreign key renders a link to its change view"):
            self.assertEqual(
                organization_link(secret),
                f'<a href="{reverse("admin:core_organization_change", args=[self.organization1.pk])}">org1</a>',
            )

        with self.subTest("Test an empty foreign key renders a dash"):
            self.assertEqual(project_link(secret), "-")

        with self.subTest("Test a non-foreign key in the configuration is rejected"):
            misconfigured_admin = MisconfiguredSecretAdmin(Secret, qfc_admin_site)

            with self.assertRaisesMessage(
                ImproperlyConfigured, "The field 'name' is not a foreign key."
            ):
                misconfigured_admin.get_list_display(self.request)

    def test_search_parser_filters_by_configured_prefix(self):
        with self.subTest("Test owner: matches projects of the exact owner only"):
            self.assertEqual(
                self._search_projects("owner:USER1"),
                ["project1", "public_project"],
            )

        with self.subTest(
            "Test collaborator: matches only private projects of the collaborator"
        ):
            self.assertEqual(
                self._search_projects("collaborator:user2"),
                ["project1"],
            )

        with self.subTest("Test owner: matches organizations of the exact owner only"):
            self.assertEqual(
                self._search_organizations("owner:user1"),
                ["org1"],
            )

        with self.subTest("Test member: matches organizations of the member"):
            self.assertEqual(
                self._search_organizations("member:user2"),
                ["org2"],
            )

    def test_search_parser_falls_back_to_default_search(self):
        with self.subTest("Test a search without a prefix uses the search fields"):
            self.assertEqual(
                self._search_projects("public"),
                ["public_project"],
            )

        with self.subTest("Test an unknown prefix uses the search fields literally"):
            self.assertEqual(
                self._search_projects("unknown:x"),
                [],
            )

    def test_no_pk_order_changelist_drops_the_pk_tiebreaker(self):
        ProcessProjectfileJob.objects.create(
            project=self.project1,
            created_by=self.user1,
            status=Job.Status.FAILED,
        )

        with self.subTest("Test the default ordering doesn't add -pk"):
            # Django appends the admin queryset's own `order_by` to the default ordering,
            # hence `-updated_at` twice; harmless, as the second one has no effect
            self.assertEqual(
                self._get_job_changelist_ordering({}), ["-updated_at", "-updated_at"]
            )

        with self.subTest("Test sorting by a column doesn't add -pk"):
            self.assertEqual(
                self._get_job_changelist_ordering({"o": "3"}),
                ["type", "-updated_at"],
            )
