import datetime
import logging

from django.contrib.admin import utils as django_admin_utils
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone, translation
from django_tables2 import Table
from unfold import utils as unfold_utils
from unfold.templatetags import unfold_list

from qfieldcloud.core.datetime_tooltip import DateTimeTooltipColumn
from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

FIXED_DATETIME = datetime.datetime(2026, 11, 13, 15, 37, tzinfo=datetime.UTC)
FIXED_DATETIME_ATTRS = (
    'data-qfc-datetime-tooltip="2026-11-13T15:37:00+00:00" data-tz="Europe/Sofia"'
)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.superuser.useraccount.timezone = "Europe/Sofia"
        self.superuser.useraccount.save()
        Person.objects.filter(pk=self.superuser.pk).update(date_joined=FIXED_DATETIME)

        self.project = Project.objects.create(name="project", owner=self.superuser)
        Project.objects.filter(pk=self.project.pk).update(created_at=FIXED_DATETIME)

    def test_datetime_tooltip_attrs_template_filter(self):
        template = Template(
            "<span {{ value|datetime_tooltip_attrs }}>3 days ago</span>"
        )

        with self.subTest("Test the filter renders the tooltip attributes unescaped"):
            with timezone.override("Europe/Sofia"):
                rendered = template.render(Context({"value": FIXED_DATETIME}))

            self.assertEqual(
                rendered, f"<span {FIXED_DATETIME_ATTRS}>3 days ago</span>"
            )

        with self.subTest(
            "Test the filter writes the full timezone name, not its abbreviation"
        ):
            with timezone.override("Asia/Phnom_Penh"):
                rendered = template.render(Context({"value": FIXED_DATETIME}))

            self.assertEqual(
                rendered,
                '<span data-qfc-datetime-tooltip="2026-11-13T15:37:00+00:00" '
                'data-tz="Asia/Phnom_Penh">3 days ago</span>',
            )

        with self.subTest("Test the filter renders nothing for a naive datetime"):
            rendered = template.render(
                Context({"value": FIXED_DATETIME.replace(tzinfo=None)})
            )

            self.assertEqual(rendered, "<span >3 days ago</span>")

        with self.subTest("Test the filter renders nothing for a missing value"):
            rendered = template.render(Context({"value": None}))

            self.assertEqual(rendered, "<span >3 days ago</span>")

    def test_admin_display_functions_render_tooltip_anchors(self):
        created_at_field = Project._meta.get_field("created_at")
        expected_html = f"<time {FIXED_DATETIME_ATTRS}>Nov. 13, 2026, 5:37 p.m.</time>"

        with self.subTest("Test Django's `display_for_value` wraps the admin's text"):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = django_admin_utils.display_for_value(FIXED_DATETIME, "-")

            self.assertEqual(html, expected_html)

        with self.subTest("Test Unfold's `display_for_field` wraps the admin's text"):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = unfold_utils.display_for_field(
                    FIXED_DATETIME, created_at_field, "-"
                )

            self.assertEqual(html, expected_html)

        with self.subTest(
            "Test a module importing `display_for_field` by name gets the wrapper"
        ):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = unfold_list.display_for_field(
                    FIXED_DATETIME, created_at_field, "-"
                )

            self.assertEqual(html, expected_html)

        with self.subTest("Test a naive datetime keeps the plain text"):
            with translation.override("en"):
                html = django_admin_utils.display_for_value(
                    FIXED_DATETIME.replace(tzinfo=None), "-"
                )

            self.assertEqual(html, "Nov. 13, 2026, 3:37 p.m.")

        with self.subTest("Test a non-datetime value keeps the original display"):
            html = django_admin_utils.display_for_value(None, "-")

            self.assertEqual(html, "-")

    def test_admin_pages_show_datetimes_as_tooltip_anchors(self):
        self.client.force_login(self.superuser)

        with self.subTest("Test the changelist wraps the `created_at` column"):
            response = self.client.get(reverse("admin:project_project_changelist"))

            self.assertContains(response, f"<time {FIXED_DATETIME_ATTRS}>")

        with self.subTest("Test the change view wraps the readonly `created_at` field"):
            response = self.client.get(
                reverse("admin:project_project_change", args=[self.project.pk])
            )

            self.assertContains(response, f"<time {FIXED_DATETIME_ATTRS}>")

    def test_global_search_shows_datetimes_as_tooltip_anchors(self):
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("admin:global_search"), {"q": "super@example.com"}
        )

        self.assertContains(
            response,
            f"<td {FIXED_DATETIME_ATTRS}>Nov. 13, 2026, 5:37 p.m.</td>",
            count=2,
        )

    def test_table_datetime_columns_render_tooltip_anchors(self):
        class ProjectTable(Table):
            class Meta:
                model = Project
                fields = ("created_at",)

        with self.subTest(
            "Test a column generated from a `DateTimeField` is a tooltip column"
        ):
            self.assertIsInstance(
                ProjectTable.base_columns["created_at"], DateTimeTooltipColumn
            )

        with self.subTest("Test the column wraps `DateTimeColumn`'s short format"):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = ProjectTable(Project.objects.all()).as_html(
                    RequestFactory().get("/")
                )

            self.assertIn(
                f"<time {FIXED_DATETIME_ATTRS}>11/13/2026 5:37 p.m.</time>", html
            )
