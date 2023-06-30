from io import StringIO
from os import environ
from unittest import skipIf

from rest_framework.test import APITestCase

from ..utils2.sentry import report_serialization_diff_to_sentry


class QfcTestCase(APITestCase):
    @skipIf(
        environ.get("SENTRY_DSN", False),
        "Do not run this test when Sentry's DSN is not set.",
    )
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
        will_be_sent = report_serialization_diff_to_sentry(**mock_payload)
        self.assertTrue(will_be_sent)
