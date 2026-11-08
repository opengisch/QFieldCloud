import base64
import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite

from qfc_worker.sealed_box import SealedBoxError, generate_key_pair, unseal

# NOTE this value was sealed by `docker-app/qfieldcloud/core/sealed_box.py`, it ensures the worker can open what the app seals.
TEST_VECTOR_PRIVATE_KEY = "0GWU0kJN1BsxP58NWnB-01kyXGMytAR0A7FjLX9xv3Q="
TEST_VECTOR_SEALED = "v1.POd15TMsASM0iqxzlw_8kpPNeF2vvoz8ESvhIVIEwXk1DOoDJ_KwH_5eoOPUYt5q7PBBpro_NE0OBcwR423ele9EjiLXAkxua_Lw6Hhfb4J7i8OWXGAsI3ohGKZ3VWlQ4qio2DiMAw=="
TEST_VECTOR_PLAINTEXT = "[pg_service_test]\nhost=db.example.com\npassword=grüezi\n"

X25519_KEY_LENGTH = 32


def _seal(public_key: str, plaintext: str) -> str:
    """Seals `plaintext` the way the app does.

    NOTE the format is deliberately written out here and not shared, the app has the same guard in
    `docker-app/qfieldcloud/core/tests/test_sealed_box.py`.
    """
    suite = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)
    ciphertext = suite.encrypt(
        plaintext.encode("utf-8"),
        X25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(public_key)),
        info=b"qfc-sealed-secret-v1",
    )

    return _sealed_from_ciphertext(ciphertext)


def _test_vector_ciphertext() -> bytes:
    return base64.urlsafe_b64decode(TEST_VECTOR_SEALED.split(".")[1])


def _sealed_from_ciphertext(ciphertext: bytes) -> str:
    return f"v1.{base64.urlsafe_b64encode(ciphertext).decode('ascii')}"


class SealedBoxTestCase(unittest.TestCase):
    def test_unseal_test_vector(self):
        self.assertEqual(
            unseal(private_key=TEST_VECTOR_PRIVATE_KEY, sealed=TEST_VECTOR_SEALED),
            TEST_VECTOR_PLAINTEXT,
        )

    def test_generated_key_pair_opens_sealed_value(self):
        private_key, public_key = generate_key_pair()

        sealed = _seal(public_key, TEST_VECTOR_PLAINTEXT)

        self.assertEqual(
            unseal(private_key=private_key, sealed=sealed), TEST_VECTOR_PLAINTEXT
        )

    def test_unseal_with_wrong_private_key_fails(self):
        public_key = generate_key_pair().public_key
        other_private_key = generate_key_pair().private_key

        with self.assertRaises(SealedBoxError):
            unseal(private_key=other_private_key, sealed=_seal(public_key, "value"))

    def test_unseal_with_tampered_ciphertext_fails(self):
        ciphertext = _test_vector_ciphertext()

        for position in [0, len(ciphertext) // 2, -1]:
            tampered = bytearray(ciphertext)
            tampered[position] ^= 1

            with self.subTest(position=position):
                with self.assertRaises(SealedBoxError):
                    unseal(
                        private_key=TEST_VECTOR_PRIVATE_KEY,
                        sealed=_sealed_from_ciphertext(bytes(tampered)),
                    )

    def test_unseal_with_low_order_encapsulated_key_fails(self):
        ciphertext = _test_vector_ciphertext()
        replaced = bytes(X25519_KEY_LENGTH) + ciphertext[X25519_KEY_LENGTH:]

        with self.assertRaises(SealedBoxError):
            unseal(
                private_key=TEST_VECTOR_PRIVATE_KEY,
                sealed=_sealed_from_ciphertext(replaced),
            )

    def test_unseal_with_invalid_format_fails(self):
        _version, ciphertext = TEST_VECTOR_SEALED.split(".")

        for sealed in [
            "",
            "v1",
            "v1.",
            "v1.AAAA",
            "v1.é",
            f"v2.{ciphertext}",
            f"v1.{ciphertext}.extra",
            f"v1.{ciphertext[:10]}!!{ciphertext[10:]}",
        ]:
            with self.subTest(sealed=sealed):
                with self.assertRaises(SealedBoxError):
                    unseal(private_key=TEST_VECTOR_PRIVATE_KEY, sealed=sealed)

    def test_unseal_with_invalid_private_key_fails(self):
        for private_key in ["", "é", "not-base64!", "c2hvcnQ="]:
            with self.subTest(private_key=private_key):
                with self.assertRaises(SealedBoxError):
                    unseal(private_key=private_key, sealed=TEST_VECTOR_SEALED)
