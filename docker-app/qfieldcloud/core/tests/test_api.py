import logging
import time
from urllib import parse

from django.core.cache import cache
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.pagination import LimitOffsetPagination
from qfieldcloud.core.views.projects_views import ProjectViewSet
from rest_framework import status
from rest_framework.test import (
    APIRequestFactory,
    APITransactionTestCase,
    force_authenticate,
)

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
        projects = [
            Project(name=f"project{n}", is_public=True, owner=self.user)
            for n in range(500)
        ]
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
        expected_count = Project.objects.all().count()
        self.assertEqual(expected_count, 500)

        # picked randomly: ProjectViewSet
        ProjectViewSet.pagination_class = LimitOffsetPagination
        view = ProjectViewSet.as_view({"get": "list"})
        factory = APIRequestFactory()
        page_size = 35

        # obtain response with LIMIT
        request_with_pagination = factory.get("/api/v1/projects/", {"limit": page_size})
        force_authenticate(request_with_pagination, user=self.user, token=self.token)
        response = view(request_with_pagination)
        response_rendered = response.render()
        results_with_pagination = response_rendered.data["results"]
        self.assertEqual(len(results_with_pagination), page_size)

        # obtain response with LIMIT and OFFSET
        offset = 36
        request_with_offset = factory.get(
            "api/v1/projects/", {"limit": page_size, "offset": offset}
        )
        force_authenticate(request_with_offset, user=self.user, token=self.token)
        response = view(request_with_offset)
        response_rendered = response.render()

        # test page size
        results_with_offset = response_rendered.data["results"]
        self.assertEqual(len(results_with_offset), page_size)

        # test 'previous' params
        previous_url = response_rendered.data["previous"]
        params = parse_numeric_query_params_from_url(previous_url)
        self.assertEqual(params["limit"], 35)
        self.assertEqual(params["offset"], 1)

        # test 'next' params
        next_url = response_rendered.data["next"]
        params = parse_numeric_query_params_from_url(next_url)
        self.assertEqual(params["limit"], 35)
        self.assertEqual(params["offset"], 71)

        # obtain without pagination (aka control test)
        request_without_pagination = factory.get(
            "/api/v1/projects/",
        )
        force_authenticate(request_without_pagination, user=self.user, token=self.token)
        response = view(request_without_pagination)
        response_rendered = response.render()

        # testing length
        results_without_pagination = response_rendered.data
        self.assertEqual(len(results_without_pagination), expected_count)

    def test_api_pagination_projects(self):
        factory = APIRequestFactory()
        request = factory.get("/api/v1/projects/", {"limit": 10})
        force_authenticate(request, user=self.user, token=self.token)

        # ProjectViewSet uses 'LimitOffsetPaginationResults' by default
        view = ProjectViewSet.as_view({"get": "list"})
        response = view(request)

        response_rendered = response.render()
        self.assertEqual(len(response_rendered.data), 10)
