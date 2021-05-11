import time

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITransactionTestCase


class StatusTestCase(APITransactionTestCase):
    def setUp(self):
        # Empty cache value
        cache.delete("status_results")

    def test_api_status(self):
        response = self.client.get("/api/v1/status/")
        self.assertTrue(status.is_success(response.status_code))
        self.assertIn(response.json()["orchestrator"], ["ok", "slow"])
        self.assertEqual(response.json()["redis"], "ok")
        self.assertEqual(response.json()["storage"], "ok")
        self.assertEqual(response.json()["geodb"], "ok")

    def test_api_status_cache(self):
        tic = time.perf_counter()
        self.client.get("/api/v1/status/")
        toc = time.perf_counter()
        self.client.get("/api/v1/status/")
        tac = time.perf_counter()

        self.assertGreater(toc - tic, 1)
        self.assertLess(tac - toc, 1)
