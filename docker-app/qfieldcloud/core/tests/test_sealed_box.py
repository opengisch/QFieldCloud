import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite
from django.test import SimpleTestCase

from qfieldcloud.core.sealed_box import (
    SealedBoxError,
    seal,
    validate_public_key,
)

TEST_PRIVATE_KEY = "0GWU0kJN1BsxP58NWnB-01kyXGMytAR0A7FjLX9xv3Q="
TEST_PUBLIC_KEY = "6MzFDHAx0a-qfHUpgNla6WMlbJdZblPd4j4rxpbx5k8="
TEST_PLAINTEXT = "[pg_service_test]\nhost=db.example.com\npassword=grüezi\n"

LOW_ORDER_PUBLIC_KEY = base64.urlsafe_b64encode(bytes(32)).decode("ascii")


def _open(sealed: str) -> str:
    """Opens `sealed` the way the worker does.

    NOTE the format is deliberately written out here and not imported, so that changing the format constants in
    `sealed_box` fails this test. The worker has the same guard in `docker-qgis/qfc_worker/tests/test_sealed_box.py`.
    """
    version, ciphertext = sealed.split(".")
    assert version == "v1"

    private_key = X25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(TEST_PRIVATE_KEY)
    )
    suite = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)

    return suite.decrypt(
        base64.urlsafe_b64decode(ciphertext),
        private_key,
        info=b"qfc-sealed-secret-v1",
    ).decode("utf-8")


class QfcTestCase(SimpleTestCase):
    def test_seal_can_be_opened_with_the_worker_format(self):
        sealed = seal(public_key=TEST_PUBLIC_KEY, plaintext=TEST_PLAINTEXT)

        self.assertEqual(_open(sealed), TEST_PLAINTEXT)

    def test_validate_public_key(self):
        validate_public_key(TEST_PUBLIC_KEY)

    def test_invalid_public_key_fails(self):
        for public_key in [
            "",
            "é",
            "not-base64!",
            "c2hvcnQ=",
            f"{TEST_PUBLIC_KEY[:10]}!!{TEST_PUBLIC_KEY[10:]}",
        ]:
            with self.subTest(public_key=public_key):
                with self.assertRaises(SealedBoxError):
                    validate_public_key(public_key)

                with self.assertRaises(SealedBoxError):
                    seal(public_key=public_key, plaintext="value")

    def test_seal_with_low_order_public_key_fails(self):
        with self.assertRaises(SealedBoxError):
            seal(public_key=LOW_ORDER_PUBLIC_KEY, plaintext="value")
