import logging
import time
from urllib import parse

from django.core.cache import cache
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


def parse_numeric_query_params_from_url(url: str) -> dict[str, int]:
    parsed_url = parse.urlparse(url).query
    parsed_query = parse.parse_qs(parsed_url)
    return {k: int(v[0]) for k, v in parsed_query.items()}


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        # Empty cache value
        cache.delete("status_results")

        # Create needed subscription relations
        setup_subscription_plans()

        # Set up a user to own projects
        self.user = Person.objects.create_user(username="user1", password="abc123")
        self.token = AuthToken.objects.get_or_create(user=self.user)[0]

        # Create a bunch of public projects
        projects = (
            Project(name=f"project{n}", is_public=True, owner=self.user)
            for n in range(500)
        )
        Project.objects.bulk_create(projects)

    def test_api_status(self):
        response = self.client.get("/api/v1/status/")
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.json()["redis"], "ok")
        self.assertEqual(response.json()["storage"], "ok")
        self.assertEqual(response.json()["geodb"], "ok")

    def test_api_status_cache(self):
        tic = time.perf_counter()
        self.client.get("/api/v1/status/")
        toc = time.perf_counter()

        self.assertGreater(toc - tic, 0)

    def test_api_pagination_limitoffset(self):
        """Test LimitOffset pagination custom implementation"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        page_size = 35
        offset = 36
        unlimited_count = Project.objects.all().count()
        self.assertEqual(unlimited_count, 500)

        # Obtain response with LIMIT
        results_with_pagination = self.client.get(
            "/api/v1/projects/", {"limit": page_size}
        ).json()
        self.assertEqual(len(results_with_pagination), page_size)

        # Obtain response with LIMIT and OFFSET
        results_with_offset = self.client.get(
            "/api/v1/projects/", {"limit": page_size, "offset": offset}
        ).json()

        # Test page size
        self.assertEqual(len(results_with_offset), page_size)

        # Obtain without pagination (= control test)
        results_without_pagination = self.client.get(
            "/api/v1/projects/",
        ).json()

        # Test length (this is super slow -- 1 minute or so -- because of serialization)
        self.assertEqual(len(results_without_pagination), unlimited_count)
