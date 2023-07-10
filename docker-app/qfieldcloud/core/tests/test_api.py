import logging
import time

from django.core.cache import cache
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import pagination
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.views.projects_views import ProjectViewSet
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


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
        self.total_projects = 50
        projects = (
            Project(name=f"project{n}", is_public=True, owner=self.user)
            for n in range(self.total_projects)
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

        page_size = 5
        offset = 3
        unlimited_count = Project.objects.all().count()
        self.assertEqual(unlimited_count, self.total_projects)

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
        results_without_offset_or_request_level_limit = self.client.get(
            "/api/v1/projects/",
        ).json()

        # Even though the request is not setting a limit, the Project modelviewset
        # was defined with a default limit that's kicking in here
        self.assertEqual(
            ProjectViewSet.pagination_class.default_limit,
            len(results_without_offset_or_request_level_limit),
        )

    def test_api_headers_count(self):
        """Test LimitOffset pagination custom 'X-Total-Count' headers implementation"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        # Mutating project viewset for testing purposes
        ProjectViewSet.pagination_class = pagination.QfcLimitOffsetPagination(
            count_entries=True
        )

        response = self.client.get("/api/v1/projects/")
        self.assertEqual(
            int(response.headers["X-Total-Count"]),
            self.total_projects,
        )
