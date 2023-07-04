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
        # Set up data
        setup_subscription_plans()
        self.user = Person.objects.create_user(username="user1", password="abc123")
        self.token = AuthToken.objects.get_or_create(user=self.user)[0]
        Project.objects.create(name="project1", is_public=True, owner=self.user)
        Project.objects.create(name="project2", is_public=True, owner=self.user)

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

    def test_api_default_paginator_offset(self):
        page_size = 1
        view = ProjectViewSet.as_view({"get": "list"})
        request_with_pagination = APIRequestFactory().get(
            "/api/v1/projects/", {"limit": page_size}
        )
        force_authenticate(request_with_pagination, user=self.user, token=self.token)
        response = view(request_with_pagination)
        response_rendered = response.render()
        results_with_pagination = response_rendered.data["results"]

        request_without_pagination = APIRequestFactory().get(
            "/api/v1/projects/",
        )
        force_authenticate(request_without_pagination, user=self.user, token=self.token)
        response = view(request_without_pagination)
        response_rendered = response.render()
        results_without_pagination = response_rendered.data

        with self.subTest():
            self.assertEqual(len(results_with_pagination), page_size)
            self.assertEqual(
                len(results_without_pagination), Project.objects.all().count()
            )
