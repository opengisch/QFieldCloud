import logging
import time

from django.core.cache import cache
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.views.projects_views import ProjectViewSet
from rest_framework import status
from rest_framework.test import (
    APIRequestFactory,
    APITransactionTestCase,
    force_authenticate,
)

from .utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        # Empty cache value
        cache.delete("status_results")

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

    def test_api_default_paginator(self):
        setup_subscription_plans()
        user1 = Person.objects.create_user(username="user1", password="abc123")
        token = AuthToken.objects.get_or_create(user=user1)[0]

        Project.objects.create(name="project1", is_public=True, owner=user1)
        Project.objects.create(name="project2", is_public=True, owner=user1)

        items_per_page = 1
        view = ProjectViewSet.as_view({"get": "list"})
        request = APIRequestFactory().get(
            "/api/v1/projects/", {"items_per_page": items_per_page}
        )
        force_authenticate(request, user=user1, token=token)
        response = view(request)
        response_rendered = response.render()
        results = response_rendered.data["results"]
        self.assertEqual(len(results), items_per_page)
