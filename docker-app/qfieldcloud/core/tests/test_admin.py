import logging

from bs4 import BeautifulSoup
from django.conf import settings
from django.test.testcases import TransactionTestCase
from django.urls.resolvers import URLPattern, URLResolver

from ..models import Delta, Organization, Person, ProcessProjectfileJob, Project, Team
from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


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


class QfcTestCase(TransactionTestCase):
    def setUp(self):
        setup_subscription_plans()
        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
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
            created_by=self.superuser,
            content={},
        )

    def test_admin_opens(self):
        skip_urls = (
            "/admin/login/",
            "/admin/logout/",
            "/admin/password_change/",
            "/admin/password_change/done/",
            "/admin/autocomplete/",
            "/admin/core/delta/add/",
            "/admin/core/job/add/",
            "/admin/axes/accessattempt/add/",
            "/admin/axes/accessfailurelog/add/",
            "/admin/axes/accesslog/add/",
            "/admin/auditlog/logentry/add/",
        )
        # TODO make tests pass for these sortable URLs
        skip_sort_urls = ("/admin/django_cron/cronjoblog/?o=4",)

        self.client.force_login(self.superuser)

        urlconf = __import__(settings.ROOT_URLCONF, {}, {}, [""])

        for url_item in list_urls(urlconf.urlpatterns):
            if url_item[0] != "admin/":
                continue

            url = "/" + "".join(url_item)

            # skip if the URL pattern contains placeholders, e.g. /admin/app/model/<object_id>/edit
            if "<" in url:
                continue

            if url in skip_urls:
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
            for anchor in soup.select("th.sortable a"):
                sort_url = f"{url}{anchor.get('href')}"

                if sort_url in skip_sort_urls:
                    continue

                resp = self.client.get(sort_url)
                self.assertEqual(
                    resp.status_code,
                    200,
                    f'Failed to sort "{sort_url}", got HTTP {resp.status_code}.',
                )
