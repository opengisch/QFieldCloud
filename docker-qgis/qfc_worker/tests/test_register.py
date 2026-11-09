import unittest
from unittest import mock

import requests

from qfc_worker.register import RegisterError, register
from qfc_worker.sealed_box import unseal
from qfc_worker.tests.test_sealed_box import _seal

URL = "https://example.com/api/v1/"
CREDENTIAL = "credential"


def _response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code

    return response


class TestRegister(unittest.TestCase):
    @mock.patch("qfc_worker.register.requests.put")
    def test_sends_public_key_of_the_returned_key_pair(self, put):
        put.return_value = _response(204)

        key_pair = register(URL, CREDENTIAL)

        put.assert_called_once()
        self.assertEqual(
            put.call_args.args[0], "https://example.com/api/v1/worker/key/"
        )
        self.assertEqual(
            put.call_args.kwargs["headers"], {"Authorization": "WorkerPool credential"}
        )
        sent_public_key = put.call_args.kwargs["json"]["public_key"]
        self.assertEqual(
            unseal(
                private_key=key_pair.private_key,
                sealed=_seal(sent_public_key, "value"),
            ),
            "value",
        )

    @mock.patch("qfc_worker.register.requests.put")
    def test_private_key_is_not_sent(self, put):
        put.return_value = _response(204)

        key_pair = register(URL, CREDENTIAL)

        self.assertNotIn(key_pair.private_key, str(put.call_args))

    @mock.patch("qfc_worker.register.requests.put")
    def test_refused_requests_raise(self, put):
        for status_code in (401, 409, 500):
            with self.subTest(status_code=status_code):
                put.return_value = _response(status_code)

                with self.assertRaises(RegisterError):
                    register(URL, CREDENTIAL)

    @mock.patch("qfc_worker.register.requests.put")
    def test_connection_error_raises(self, put):
        put.side_effect = requests.ConnectionError("no route")

        with self.assertRaises(RegisterError):
            register(URL, CREDENTIAL)
