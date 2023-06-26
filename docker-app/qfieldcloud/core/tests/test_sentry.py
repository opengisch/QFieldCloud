from io import StringIO

from rest_framework.test import APITestCase

from ..utils2.sentry import report_serialization_diff_to_sentry


class QfcTestCase(APITestCase):
    def test_logging_with_sentry(self):
        mock_payload = {
            "name": "request_id_file_name",
            "pre_serialization": str({
                "data": ["some", "pre-serialization", "data", "keys"],
                "files": ["some", "files", "to be", "listed"],
                "meta": ["metadata", "of the request pre-serialization"],
            }),
            "post_serialization": str({
                "data": ["some", "post-serialization", "data", "keys"],
                "files": ["some", "files", "to be", "listed"],
                "meta": {"metadata": "of the request post-serialization"},
            }),
            "buffer": StringIO("The traceback of the exception to raise"),
        }
        result = report_serialization_diff_to_sentry(**mock_payload)
        self.assertTrue(result)
