import logging
import time

from django.conf import settings
from django.core.cache import cache
from qfieldcloud.authentication.models import AuthToken
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

        # Obtain without pagination (= control test)
        results_without_offset_or_request_level_limit = self.client.get(
            "/api/v1/projects/",
        ).json()

        # Since the request is not setting a limit, we can the full count of model instances
        self.assertEqual(
            len(results_without_offset_or_request_level_limit),
            self.total_projects,
        )

        page_size = 5
        offset = 3
        unlimited_count = Project.objects.all().count()

        self.assertEqual(unlimited_count, self.total_projects)

        # Obtain response with LIMIT in request
        results_with_pagination = self.client.get(
            "/api/v1/projects/", {"limit": page_size}
        ).json()
        self.assertEqual(len(results_with_pagination), page_size)

        # Obtain response with LIMIT and OFFSET in request
        results_with_offset = self.client.get(
            "/api/v1/projects/", {"limit": page_size, "offset": offset}
        ).json()
        self.assertEqual(len(results_with_offset), page_size)

        # Obtain response with OFFSET but not LIMIT (so the default model's limit kicks in)
        results_with_default_pagination = self.client.get(
            "/api/v1/projects/", {"offset": 10}
        ).json()
        self.assertEqual(
            len(results_with_default_pagination),
            settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT,
        )

    def test_api_headers_count(self):
        """Test LimitOffset pagination custom 'X-Total-Count' headers implementation"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        # Get paginated response with X-Total-Count as header
        response = self.client.get("/api/v1/projects/", {"limit": 25})
        self.assertEqual(
            int(response.headers["X-Total-Count"]),
            self.total_projects,
        )

        # Get unpaginated response without X-Total-Count as header
        response = self.client.get("/api/v1/projects/")
        self.assertNotIn("X-Total-Count", response.headers)

    def test_api_pagination_controls(self):
        """Test opt-in pagination controls"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        # Set up viewset
        ProjectViewSet.pagination_class.pagination_controls_in_response = True

        # Get paginated response with controls in responses
        response = self.client.get("/api/v1/projects/", {"limit": 20})
        data = response.json()

        # Controls
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 20)

        # Next
        next_url = f"/{data['next'].split('/', 3)[3]}"
        next_data = self.client.get(next_url).json()
        self.assertEqual(len(next_data["results"]), 20)

        # Previous
        previous_url = f"/{next_data['previous'].split('/', 3)[3]}"
        previous_data = self.client.get(previous_url).json()
        self.assertEqual(len(previous_data["results"]), 20)

        # Traverse in both directions: Next
        items = set({el["id"] for el in data["results"]})
        while current_url := data["next"]:
            data = self.client.get(current_url).json()
            items.update({el["id"] for el in data["results"]})
        self.assertEqual(len(items), 50)

        # Traverse in both directions: Previous
        items = set({el["id"] for el in data["results"]})
        while current_url := data["previous"]:
            data = self.client.get(current_url).json()
            items.update({el["id"] for el in data["results"]})
        self.assertEqual(len(items), 50)
