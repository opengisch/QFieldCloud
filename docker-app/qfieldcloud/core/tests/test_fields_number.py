from unittest.mock import patch

from django.test import TestCase


class QfcTestCase(TestCase):
    def _create_request_data(self, n: int) -> dict:
        """Helper method to create a dummy dictionary with n fields."""
        result = {}

        for i in range(n):
            result[f"field_{i}"] = f"value_{i}"

        return result

    def test_too_many_parameters_fail(self):
        with patch("qfieldcloud.core.middleware.fields_limit.config") as mock_config:
            mock_config.WEB_DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

            response = self.client.get(
                "/api/v1/status/", query_params=self._create_request_data(1001)
            )

            # Django throws a `django.core.exceptions.TooManyFieldsSent` exception, with message :
            # `The number of GET/POST parameters exceeded settings.DATA_UPLOAD_MAX_NUMBER_FIELDS.`
            # somehow, the test does not catch with a `self.assertRaises(TooManyFieldsSent)`
            self.assertNotEqual(response.status_code, 200)
            self.assertEqual(response.status_code, 400)

    def test_many_parameters_ok_when_constance_limit_set_bigger(self):
        with patch("qfieldcloud.core.middleware.fields_limit.config") as mock_config:
            mock_config.WEB_DATA_UPLOAD_MAX_NUMBER_FIELDS = 1010

            response = self.client.get(
                "/api/v1/status/", query_params=self._create_request_data(1001)
            )

            self.assertEqual(response.status_code, 200)
