"""Opening of secrets sealed for a worker pool.

The worker generates the key pair of its pool and is the only place that ever holds the private key.
The QFieldCloud app seals secrets with the public key and cannot decrypt them afterwards.

The construction is HPKE (RFC 9180) in base mode, with DHKEM(X25519, HKDF-SHA256), HKDF-SHA256 and AES-256-GCM.

The sealed value is the text `v1.<base64url HPKE ciphertext>`.
The keys are the base64url encoding of the raw X25519 keys.

NOTE the sealing half is in `docker-app/qfieldcloud/core/sealed_box.py`, the format constants must stay the same on both sides.
"""

import base64
from typing import NamedTuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite

# NOTE a new version must get its own suite and info, and `unseal` must keep accepting the older versions.
SEALED_BOX_VERSION = "v1"
HPKE_SUITE = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)
HPKE_INFO = b"qfc-sealed-secret-v1"


class SealedBoxError(ValueError):
    """Raised when a private key or a sealed value is malformed, or the sealed value cannot be opened."""


class KeyPair(NamedTuple):
    """A base64url encoded key pair of a worker pool."""

    private_key: str
    public_key: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except ValueError as err:
        raise SealedBoxError("Invalid base64url value.") from err

    # `urlsafe_b64decode` silently discards invalid characters, accept only the canonical encoding.
    if _encode(decoded) != value:
        raise SealedBoxError("Invalid base64url value.")

    return decoded


def _load_private_key(private_key: str) -> X25519PrivateKey:
    try:
        return X25519PrivateKey.from_private_bytes(_decode(private_key))
    except ValueError as err:
        raise SealedBoxError("Invalid worker pool private key.") from err


def generate_key_pair() -> KeyPair:
    """Generates a new key pair for a worker pool.

    Returns:
        the base64url encoded private and public keys.
    """
    private_key = X25519PrivateKey.generate()

    return KeyPair(
        private_key=_encode(private_key.private_bytes_raw()),
        public_key=_encode(private_key.public_key().public_bytes_raw()),
    )


def unseal(*, private_key: str, sealed: str) -> str:
    """Decrypts a value sealed by the QFieldCloud app.

    Args:
        private_key: the base64url encoded private key of the worker pool.
        sealed: the sealed value.

    Returns:
        the decrypted plaintext.

    Raises:
        SealedBoxError: if the private key or the sealed value is malformed, or the value cannot be opened.
    """
    parts = sealed.split(".")

    if len(parts) != 2 or parts[0] != SEALED_BOX_VERSION:
        raise SealedBoxError("Invalid sealed value format.")

    recipient_private_key = _load_private_key(private_key)
    ciphertext = _decode(parts[1])

    try:
        return HPKE_SUITE.decrypt(
            ciphertext, recipient_private_key, info=HPKE_INFO
        ).decode("utf-8")
    except (InvalidTag, ValueError) as err:
        raise SealedBoxError("Failed to open the sealed value.") from err
