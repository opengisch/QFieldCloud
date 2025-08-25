import logging

from django.conf import settings
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
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

        # Get unpaginated response without X-Total-Count in headers
        response = self.client.get("/api/v1/projects/")
        self.assertNotIn("X-Total-Count", response.headers)

    def test_api_pagination_controls(self):
        """Test opt-in pagination controls"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        # Get paginated response with controls in responses
        response = self.client.get("/api/v1/projects/", {"limit": 20})

        # Next
        next_url = f"/{response.headers['X-Next-Page'].split('/', 3)[3]}"
        next_response = self.client.get(next_url)
        next_data = next_response.json()
        self.assertEqual(len(next_data), 20)

        # Previous
        previous_url = f"/{next_response.headers['X-Previous-Page'].split('/', 3)[3]}"
        previous_response = self.client.get(previous_url)
        previous_data = previous_response.json()
        self.assertEqual(len(previous_data), 20)

        # Neither when results are not paginated
        response = self.client.get("/api/v1/projects/")
        self.assertNotIn("X-Next-Page", response.headers)
        self.assertNotIn("X-Previous-Page", response.headers)
        self.assertNotIn("X-Total-Count", response.headers)

    def test_api_pagination_traversals(self):
        """Test opt-in pagination traversals"""
        # Authenticate client
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token.key)

        # Traverse in both directions: Next
        response = self.client.get("/api/v1/projects/", {"limit": 20})
        data = response.json()

        items = {el["id"] for el in data}
        next_url = response.headers.get("X-Next-Page")

        while next_url:
            response = self.client.get(next_url)
            results = response.json()
            items.update({el["id"] for el in results})
            next_url = response.headers.get("X-Next-Page")

        self.assertEqual(len(items), self.total_projects)

        # Traverse in both directions: Previous
        response = self.client.get(
            "/api/v1/projects/", {"limit": 20, "offset": self.total_projects}
        )

        items.clear()
        previous_url = response.headers.get("X-Previous-Page")

        while previous_url:
            response = self.client.get(previous_url)
            results = response.json()
            items.update({el["id"] for el in results})
            previous_url = response.headers.get("X-Previous-Page")

        self.assertEqual(len(items), self.total_projects)
