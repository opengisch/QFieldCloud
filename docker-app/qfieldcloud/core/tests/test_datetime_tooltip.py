import datetime
import logging

from django.contrib.admin import utils as django_admin_utils
from django.template import Context, Template
from django.test import TestCase
from django.utils import timezone, translation
from unfold.templatetags import unfold_list

from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

FIXED_DATETIME = datetime.datetime(2026, 11, 13, 15, 37, tzinfo=datetime.UTC)
FIXED_DATETIME_ATTRS = (
    'data-qfc-datetime-tooltip="2026-11-13T15:37:00+00:00" data-tz="Europe/Sofia"'
)


def render(template_code: str, value: object) -> str:
    return Template(template_code).render(Context({"value": value}))


class QfcTestCase(TestCase):
    def test_datetime_template_filter(self):
        with self.subTest("Test the filter localizes the datetime like the admin"):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = render("{{ value|datetime }}", FIXED_DATETIME)

            self.assertEqual(
                html, f"<span {FIXED_DATETIME_ATTRS}>Nov. 13, 2026, 5:37 p.m.</span>"
            )

        with self.subTest('Test the filter formats like `|date` with "date"'):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = render('{{ value|datetime:"date" }}', FIXED_DATETIME)

            self.assertEqual(html, f"<span {FIXED_DATETIME_ATTRS}>Nov. 13, 2026</span>")

        with self.subTest("Test the filter applies a custom date format string"):
            with timezone.override("Europe/Sofia"):
                html = render('{{ value|datetime:"d.m.Y H:i" }}', FIXED_DATETIME)

            self.assertEqual(
                html, f"<span {FIXED_DATETIME_ATTRS}>13.11.2026 17:37</span>"
            )

        with self.subTest('Test the filter formats like `|timesince` with "timesince"'):
            three_days_ago = timezone.now() - datetime.timedelta(days=3)

            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = render('{{ value|datetime:"timesince" }}', three_days_ago)

            self.assertEqual(
                html,
                f'<span data-qfc-datetime-tooltip="{three_days_ago.isoformat()}" '
                'data-tz="Europe/Sofia">3\xa0days</span>',
            )

        with self.subTest(
            "Test the filter writes the full timezone name, not its abbreviation"
        ):
            with timezone.override("Asia/Phnom_Penh"):
                html = render('{{ value|datetime:"d.m.Y H:i" }}', FIXED_DATETIME)

            self.assertEqual(
                html,
                '<span data-qfc-datetime-tooltip="2026-11-13T15:37:00+00:00" '
                'data-tz="Asia/Phnom_Penh">13.11.2026 22:37</span>',
            )

        with self.subTest("Test the filter keeps a naive datetime as plain text"):
            with translation.override("en"):
                html = render(
                    "{{ value|datetime }}", FIXED_DATETIME.replace(tzinfo=None)
                )

            self.assertEqual(html, "Nov. 13, 2026, 3:37 p.m.")

        with self.subTest("Test `|default` applies to a missing value"):
            html = render('{{ value|datetime|default:"-" }}', None)

            self.assertEqual(html, "-")

    def test_admin_display_functions_render_tooltip_anchors(self):
        created_at_field = Project._meta.get_field("created_at")
        expected_html = f"<span {FIXED_DATETIME_ATTRS}>Nov. 13, 2026, 5:37 p.m.</span>"

        with self.subTest("Test Django's `display_for_value` wraps the admin's text"):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = django_admin_utils.display_for_value(FIXED_DATETIME, "-")

            self.assertEqual(html, expected_html)

        with self.subTest(
            "Test a module importing `display_for_field` by name gets the wrapper"
        ):
            with timezone.override("Europe/Sofia"), translation.override("en"):
                html = unfold_list.display_for_field(
                    FIXED_DATETIME, created_at_field, "-"
                )

            self.assertEqual(html, expected_html)

        with self.subTest("Test a non-datetime value keeps the original display"):
            html = django_admin_utils.display_for_value(None, "-")

            self.assertEqual(html, "-")
