import logging
import time
from datetime import datetime

from constance import config
from constance.test import override_config
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.views.status_views import StatusValue

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        # Empty cache value
        cache.clear()

    def test_status_api(self):
        response = self.client.get("/api/v1/status/")

        self.assertTrue(status.is_success(response.status_code))

        data = response.json()

        self.assertIn("database", data)
        self.assertEqual(data["database"], StatusValue.OK)

        self.assertIn("storage", data)
        self.assertEqual(data["storage"], StatusValue.OK)

        self.assertIn("status_page_url", data)
        self.assertEqual(data["status_page_url"], config.STATUS_PAGE_URL)

        self.assertIn("incident_timestamp_utc", data)
        self.assertIsNone(data["incident_timestamp_utc"])

        self.assertIn("incident_message", data)
        self.assertIsNone(data["incident_message"])

    @override_settings(STORAGES={})
    def test_status_storage_fails_with_no_storages(self):
        response = self.client.get("/api/v1/status/")

        self.assertTrue(status.is_success(response.status_code))

        data = response.json()

        self.assertIn("database", data)
        self.assertEqual(data["database"], StatusValue.OK)

        self.assertIn("storage", data)
        self.assertEqual(data["storage"], StatusValue.ERROR)

        self.assertIn("status_page_url", data)
        self.assertEqual(data["status_page_url"], config.STATUS_PAGE_URL)

        self.assertIn("incident_timestamp_utc", data)
        self.assertIsNone(data["incident_timestamp_utc"])

        self.assertIn("incident_message", data)
        self.assertIsNone(data["incident_message"])

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "qfieldcloud.filestorage.backend.QfcS3Boto3Storage",
                "OPTIONS": {
                    "access_key": "minioadmin",
                    "secret_key": "minioadmin",
                    "bucket_name": "nonexistent-bucket",
                    "region_name": "",
                    "endpoint_url": "http://wrong.url",
                },
                "QFC_IS_LEGACY": False,
            }
        }
    )
    def test_status_storage_fails_with_wrong_config(self):
        response = self.client.get("/api/v1/status/")

        self.assertTrue(status.is_success(response.status_code))

        data = response.json()

        self.assertIn("database", data)
        self.assertEqual(data["database"], StatusValue.OK)

        self.assertIn("storage", data)
        self.assertEqual(data["storage"], StatusValue.ERROR)

        self.assertIn("status_page_url", data)
        self.assertEqual(data["status_page_url"], config.STATUS_PAGE_URL)

        self.assertIn("incident_timestamp_utc", data)
        self.assertIsNone(data["incident_timestamp_utc"])

        self.assertIn("incident_message", data)
        self.assertIsNone(data["incident_message"])

    @override_config(
        INCIDENT_IS_ACTIVE=True,
        INCIDENT_MESSAGE="Sample incident message.",
        INCIDENT_TIMESTAMP_UTC=datetime(2002, 10, 18, 12, 0, 0),
    )
    def test_status_with_active_incident(self):
        response = self.client.get("/api/v1/status/")

        self.assertTrue(status.is_success(response.status_code))

        data = response.json()

        self.assertIn("database", data)
        self.assertEqual(data["database"], StatusValue.OK)

        self.assertIn("storage", data)
        self.assertEqual(data["storage"], StatusValue.OK)

        self.assertIn("status_page_url", data)
        self.assertEqual(data["status_page_url"], config.STATUS_PAGE_URL)

        self.assertIn("incident_message", data)
        self.assertEqual(data["incident_message"], "Sample incident message.")

        self.assertIn("incident_timestamp_utc", data)
        self.assertEqual(data["incident_timestamp_utc"], "2002-10-18T12:00:00")

    @override_config(
        INCIDENT_IS_ACTIVE=False,
        INCIDENT_MESSAGE="Sample incident message.",
        INCIDENT_TIMESTAMP_UTC=datetime(2002, 10, 18, 12, 0, 0),
    )
    def test_status_with_inactive_incident(self):
        response = self.client.get("/api/v1/status/")

        self.assertTrue(status.is_success(response.status_code))

        data = response.json()

        self.assertIn("database", data)
        self.assertEqual(data["database"], StatusValue.OK)

        self.assertIn("storage", data)
        self.assertEqual(data["storage"], StatusValue.OK)

        self.assertIn("status_page_url", data)
        self.assertEqual(data["status_page_url"], config.STATUS_PAGE_URL)

        self.assertIn("incident_message", data)
        self.assertIsNone(data["incident_message"])

        self.assertIn("incident_timestamp_utc", data)
        self.assertIsNone(data["incident_timestamp_utc"])

    def test_status_cache(self):
        tic = time.perf_counter()
        self.client.get("/api/v1/status/")
        toc = time.perf_counter()

        self.assertGreater(toc - tic, 0)
