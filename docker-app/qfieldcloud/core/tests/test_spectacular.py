import yaml
from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class QfcTestCase(TestCase):
    def test_openapi_schema_generation(self):
        response = self.client.get(reverse("openapi_schema"))

        self.assertEqual(response.status_code, 200)

    def test_no_admin_prefixed_url_in_openapi_schema(self):
        response = self.client.get(reverse("openapi_schema"))

        openapi_schema = yaml.safe_load(response.content)
        endpoint_paths = openapi_schema.get("paths", {})

        for endpoint_path in endpoint_paths.keys():
            self.assertFalse(
                endpoint_path.startswith(f"/{settings.QFIELDCLOUD_ADMIN_URI}")
            )
            self.assertNotIn(settings.QFIELDCLOUD_ADMIN_URI, endpoint_path)
