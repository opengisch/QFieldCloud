import csv
import io
import logging

from allauth.account.models import EmailAddress
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.test.testcases import TransactionTestCase
from django.urls import reverse
from django.urls.resolvers import URLPattern, URLResolver
from unfold.admin import ModelAdmin

from qfieldcloud.core.admin import SecretAdmin, qfc_admin_site
from qfieldcloud.core.models import (
    Delta,
    Organization,
    OrganizationMember,
    Person,
    ProcessProjectfileJob,
    ProjectCollaborator,
    Secret,
    Team,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.enums import ProjectCollaboratorRole
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

# matches the changelist column sort links regardless of the admin theme, since the `th` classes differ between themes
SORT_LINK_SELECTOR = 'thead th a[href^="?o="]'


def list_urls(url_items, prefixes=None):
    if prefixes is None:
        prefixes = []

    if not url_items:
        return

    url_item = url_items[0]

    if isinstance(url_item, URLPattern):
        yield prefixes + [str(url_item.pattern)]
    elif isinstance(url_item, URLResolver):
        yield from list_urls(url_item.url_patterns, prefixes + [str(url_item.pattern)])

    yield from list_urls(url_items[1:], prefixes)


class MisconfiguredSecretAdmin(SecretAdmin):
    list_display_auto_fkey_fields = ("name",)


class QfcTestCase(TransactionTestCase):
    def setUp(self):
        setup_subscription_plans()
        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1@example.com"
        )
        self.user2 = Person.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )

        # we need to create these objects to be able to test sort by column
        self.project = Project.objects.create(
            name="project",
            owner=self.superuser,
        )
        self.organization = Organization.objects.create(
            username="organization",
            organization_owner=self.superuser,
        )
        self.team = Team.objects.create(
            username="@organization/team",
            team_organization=self.organization,
        )
        self.job = ProcessProjectfileJob.objects.create(
            project=self.project,
            created_by=self.superuser,
        )
        self.delta = Delta.objects.create(
            deltafile_id="f85b4d28-2444-40ce-95a8-6502bf4f00d9",
            project=self.project,
            client_id="f85b4d28-2444-40ce-95a8-6502bf4f00d9",
            created_by=self.superuser,
            content={},
        )

    def test_all_registered_admins_are_unfold_admins(self):
        """Every admin must be based on Unfold's `ModelAdmin`, otherwise its forms and changelist miss Unfold's widgets.

        The constance `Config` admin is the only exception: `unfold.contrib.constance` styles it through templates.
        """
        non_unfold_admins = []

        for model, model_admin in qfc_admin_site._registry.items():
            if isinstance(model_admin, ModelAdmin):
                continue

            non_unfold_admins.append(model._meta.label)

        self.assertEqual(non_unfold_admins, ["constance.Config"])

    def test_admin_opens(self):
        self.client.force_login(self.superuser)

        urlconf = __import__(settings.ROOT_URLCONF, {}, {}, [""])
        checked_sort_links_count = 0

        for url_item in list_urls(urlconf.urlpatterns):
            if url_item[0] != "admin/":
                continue

            url = "/" + "".join(url_item)

            with self.subTest(f"Test {url} opens..."):
                # skip if the URL pattern contains placeholders, e.g. /admin/app/model/<object_id>/edit
                if "<" in url:
                    continue

                if url in settings.QFIELDCLOUD_TEST_SKIP_VIEW_ADMIN_URLS:
                    continue

                # get page without any sorting
                resp = self.client.get(f"{url}?o=")
                self.assertEqual(
                    resp.status_code,
                    200,
                    f'Failed to open "{url}", got HTTP {resp.status_code}.',
                )

                # check all different sort columns
                soup = BeautifulSoup(resp.content, "html.parser")

                for anchor in soup.select(SORT_LINK_SELECTOR):
                    sort_url = f"{url}{anchor.get('href')}"

                    # TODO make tests pass for these sortable URLs
                    if sort_url in settings.QFIELDCLOUD_TEST_SKIP_SORT_ADMIN_URLS:
                        continue

                    resp = self.client.get(sort_url)
                    self.assertEqual(
                        resp.status_code,
                        200,
                        f'Failed to sort "{sort_url}", got HTTP {resp.status_code}.',
                    )
                    checked_sort_links_count += 1

        # if the admin theme changes the column header markup, `SORT_LINK_SELECTOR` finds no links and no sorting gets checked
        self.assertGreater(
            checked_sort_links_count, 0, "No sortable columns found in any admin page."
        )

    def test_admin_urls_redirect_non_staff_users_to_login(self):
        self.client.force_login(self.user1)

        urlconf = __import__(settings.ROOT_URLCONF, {}, {}, [""])

        for url_item in list_urls(urlconf.urlpatterns):
            if url_item[0] != "admin/":
                continue

            url = "/" + "".join(url_item)

            with self.subTest(f"Test {url} redirects a non-staff user to login"):
                # skip if the URL pattern contains placeholders, e.g. /admin/app/model/<object_id>/edit
                if "<" in url:
                    continue

                # the admin's own login and logout views are open to everyone
                if url in ("/admin/login/", "/admin/logout/"):
                    continue

                resp = self.client.get(url)

                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp.url, f"{reverse('admin:login')}?next={url}")

    def test_global_search_finds_related_objects_of_the_searched_person(self):
        project1 = Project.objects.create(name="project1", owner=self.user1)
        project2 = Project.objects.create(name="project2", owner=self.user2)
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        org2 = Organization.objects.create(
            username="org2", organization_owner=self.user2
        )

        # user1 is related to user2's project and organization, but doesn't own them
        ProjectCollaborator.objects.create(
            collaborator=self.user1,
            project=project2,
            role=ProjectCollaboratorRole.EDITOR,
        )
        OrganizationMember.objects.create(organization=org2, member=self.user1)

        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse("admin:global_search"), {"q": "user1@example.com"}
        )
        results = resp.context["results"]

        with self.subTest("Test the view finds the searched person"):
            self.assertEqual(resp.context["person_result"], self.user1)

        with self.subTest("Test the view lists only the projects owned by the person"):
            projects = results["projects"]["page_obj"]

            # `project2`, where the person is only a collaborator, is left out
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0], project1)

        with self.subTest(
            "Test the view lists only the organizations owned by the person"
        ):
            organizations = results["organizations"]["page_obj"]

            # `org2`, where the person is only a member, is left out
            self.assertEqual(len(organizations), 1)
            self.assertEqual(organizations[0], org1)

        with self.subTest("Test the view lists only the person's own subscription"):
            subscriptions = results["subscriptions"]["page_obj"]

            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0].account.user.username, "user1")

    def test_email_address_admin_export_emails_to_csv_streams_contact_details(self):
        # the primary allauth email address takes precedence over the user's own email
        EmailAddress.objects.create(
            user=self.user1,
            email="user1-primary@example.com",
            primary=True,
            verified=True,
        )
        # users without any email are left out of the export
        Person.objects.create_user(username="user3", password="abc123", email="")
        Organization.objects.create(
            username="org1", organization_owner=self.user1, email="org1@example.com"
        )

        self.client.force_login(self.superuser)

        resp = self.client.get(
            reverse("admin:account_emailaddress_export_emails_to_csv")
        )
        content = b"".join(resp.streaming_content).decode()
        # we only compare some of the exported columns, the rest aren't worth checking
        rows = []

        for row in csv.DictReader(io.StringIO(content)):
            rows.append(
                (
                    row["username"],
                    row["type"],
                    row["email"],
                    row["verified"],
                    row["owner_username"],
                    row["owner_email"],
                )
            )

        with self.subTest("Test the export is a CSV attachment"):
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "text/csv")
            # the filename ends with a timestamp of when the export ran
            self.assertTrue(
                resp["Content-Disposition"].startswith(
                    "attachment; filename=qfc_user_email_"
                )
            )
            self.assertTrue(resp["Content-Disposition"].endswith(".csv"))

        with self.subTest("Test the export has a header row with every column"):
            self.assertEqual(
                content.splitlines()[0],
                "id,username,first_name,last_name,type,email,date_joined,last_login,"
                "has_newsletter_subscription,has_accepted_tos,verified,owner_id,"
                "owner_username,owner_email,owner_first_name,owner_last_name,"
                "owner_date_joined,owner_last_login,owner_has_newsletter_subscription,"
                "owner_has_accepted_tos",
            )

        with self.subTest(
            "Test the export lists every user with an email and their owner details"
        ):
            self.assertEqual(
                rows,
                [
                    ("superuser", "1", "super@example.com", "", "", ""),
                    ("user1", "1", "user1-primary@example.com", "True", "", ""),
                    ("user2", "1", "user2@example.com", "", "", ""),
                    (
                        "org1",
                        "2",
                        "org1@example.com",
                        "",
                        "user1",
                        "user1-primary@example.com",
                    ),
                ],
            )

    def test_add_secret_action_requires_add_secret_permission(self):
        staff_user = Person.objects.create_user(
            username="staff", password="secret", is_staff=True
        )
        self.client.force_login(staff_user)

        resp = self.client.get(
            reverse("admin:project_project_add_secret", args=[self.project.pk])
        )

        self.assertEqual(resp.status_code, 403)

    def test_list_display_auto_fkey_fields_renders_foreign_keys_as_links(self):
        request = RequestFactory().get("/")
        secret = Secret.objects.create(
            name="SECRET1",
            type=Secret.Type.ENVVAR,
            organization=self.organization,
            created_by=self.user1,
            value="value",
        )
        secret_admin = qfc_admin_site._registry[Secret]
        list_display = secret_admin.get_list_display(request)

        with self.subTest("Test only the foreign key columns are replaced"):
            plain_columns = []
            link_columns = []

            for column in list_display:
                if isinstance(column, str):
                    plain_columns.append(column)
                else:
                    link_columns.append(column.admin_order_field)

            self.assertEqual(plain_columns, ["name", "type", "created_at"])
            self.assertEqual(
                link_columns, ["assigned_to", "project", "organization", "created_by"]
            )

        project_link, organization_link = list_display[3], list_display[4]

        with self.subTest("Test a set foreign key renders a link to its change view"):
            self.assertEqual(
                organization_link(secret),
                f'<a href="{reverse("admin:core_organization_change", args=[self.organization.pk])}" class="text-link">organization</a>',
            )

        with self.subTest("Test an empty foreign key renders a dash"):
            self.assertEqual(project_link(secret), "-")

        with self.subTest("Test a non-foreign key in the configuration is rejected"):
            misconfigured_admin = MisconfiguredSecretAdmin(Secret, qfc_admin_site)

            with self.assertRaisesMessage(
                ImproperlyConfigured, "The field 'name' is not a foreign key."
            ):
                misconfigured_admin.get_list_display(request)
