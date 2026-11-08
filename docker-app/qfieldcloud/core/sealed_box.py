"""Sealing of secrets for worker pools.

Secrets are sealed with the public key of a worker pool, so that only the pool's workers can open them,
while the QFieldCloud app itself cannot decrypt them after they are saved.

The construction is HPKE (RFC 9180) in base mode, with DHKEM(X25519, HKDF-SHA256), HKDF-SHA256 and AES-256-GCM.

The sealed value is the text `v1.<base64url HPKE ciphertext>`.
The public key is the base64url encoding of the raw X25519 public key.

NOTE the opening half is in `docker-qgis/qfc_worker/sealed_box.py`, the format constants must stay the same on both sides.
"""

import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite

# NOTE a new version must get its own suite and info, and the worker must keep opening the older versions.
SEALED_BOX_VERSION = "v1"
HPKE_SUITE = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)
HPKE_INFO = b"qfc-sealed-secret-v1"


class SealedBoxError(ValueError):
    """Raised when a public key is malformed or a value cannot be sealed."""


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


def _load_public_key(public_key: str) -> X25519PublicKey:
    try:
        return X25519PublicKey.from_public_bytes(_decode(public_key))
    except ValueError as err:
        raise SealedBoxError("Invalid worker pool public key.") from err


def validate_public_key(public_key: str) -> None:
    """Ensures `public_key` is a well formed key.

    Args:
        public_key: the base64url encoded public key of a worker pool.

    Raises:
        SealedBoxError: if the public key is malformed.
    """
    _load_public_key(public_key)


def seal(*, public_key: str, plaintext: str) -> str:
    """Encrypts `plaintext` so that only the holder of the private key for `public_key` can decrypt it.

    Args:
        public_key: the base64url encoded public key of a worker pool.
        plaintext: the value to encrypt.

    Returns:
        the sealed value.

    Raises:
        SealedBoxError: if the public key is malformed or the value cannot be sealed.
    """
    recipient_public_key = _load_public_key(public_key)

    try:
        ciphertext = HPKE_SUITE.encrypt(
            plaintext.encode("utf-8"), recipient_public_key, info=HPKE_INFO
        )
    except ValueError as err:
        raise SealedBoxError("Failed to seal the value.") from err

    return f"{SEALED_BOX_VERSION}.{_encode(ciphertext)}"
