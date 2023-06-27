from io import StringIO

from rest_framework.test import APITestCase
from sentry_sdk import capture_message

from ..utils2.sentry import report_serialization_diff_to_sentry


class QfcTestCase(APITestCase):
    def test_sending_message_to_sentry(self):
        capture_message("Hello Sentry from test_sentry!")

    def test_logging_with_sentry(self):
        mock_payload = {
            "name": "request_id_file_name",
            "pre_serialization": str(
                {
                    "data": [
                        "some",
                        "pre-serialization",
                        "data",
                        "keys",
                        "日本人 中國的 ~=[]()%+{}@;’#!$_&-  éè  ;∞¥₤€",
                    ],
                    "files": ["some", "files", "to be", "listed"],
                    "meta": ["metadata", "of the request pre-serialization"],
                }
            ),
            "post_serialization": str(
                {
                    "data": [
                        "some",
                        "post-serialization",
                        "data",
                        "keys",
                        "日本人 中國的 ~=[]()%+{}@;’#!$_&-  éè  ;∞¥₤€",
                    ],
                    "files": ["some", "files", "to be", "listed"],
                    "meta": {"metadata": "of the request post-serialization"},
                }
            ),
            "buffer": StringIO("The traceback of the exception to raise"),
            "capture_message": True,  # so that sentry receives attachments even when there's no exception/event
        }
        is_sent = report_serialization_diff_to_sentry(**mock_payload)
        self.assertTrue(is_sent)
