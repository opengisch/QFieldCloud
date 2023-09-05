from io import BytesIO, StringIO
from unittest import skipIf

from django.conf import settings
from django.test import Client, TestCase

from ..utils2.sentry import report_serialization_diff_to_sentry


class QfcTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Let's set up a WSGI request the body of which we'll extract
        response = Client().post(
            "test123",
            data={"file": BytesIO(b"Hello World")},
            format="multipart",
        )
        request = response.wsgi_request
        cls.body_stream = BytesIO(request.read())  # type: ignore

    @skipIf(
        not settings.SENTRY_DSN,
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
            "body_stream": self.body_stream,
            "capture_message": True,  # so that sentry receives attachments even when there's no exception/event,
        }
        will_be_sent = report_serialization_diff_to_sentry(**mock_payload)
        self.assertTrue(will_be_sent)
