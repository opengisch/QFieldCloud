import logging

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, TestCase
from django.urls import reverse

from qfieldcloud.core.admin import SecretAdmin, qfc_admin_site
from qfieldcloud.core.models import Organization, Person, Secret
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class MisconfiguredSecretAdmin(SecretAdmin):
    list_display_auto_fkey_fields = ("name",)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.organization1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )

        self.request = RequestFactory().get("/")

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
                f'<a href="{reverse("admin:core_organization_change", args=[self.organization1.pk])}" class="text-link">org1</a>',
            )

        with self.subTest("Test an empty foreign key renders a dash"):
            self.assertEqual(project_link(secret), "-")

        with self.subTest("Test a non-foreign key in the configuration is rejected"):
            misconfigured_admin = MisconfiguredSecretAdmin(Secret, qfc_admin_site)

            with self.assertRaisesMessage(
                ImproperlyConfigured, "The field 'name' is not a foreign key."
            ):
                misconfigured_admin.get_list_display(self.request)
