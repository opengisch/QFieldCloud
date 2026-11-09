#!/usr/bin/env python3
"""Registers a worker pool with QFieldCloud, run it once per pool.

It generates the key pair of the pool and sends the public key to QFieldCloud.
The private key is printed once and must be given to all workers of the pool.

Usage: QFIELDCLOUD_URL=... QFIELDCLOUD_WORKER_POOL_CREDENTIAL=... python3 -m qfc_worker.register
"""

import os
import sys

import requests

from qfc_worker.sealed_box import KeyPair, generate_key_pair

REQUEST_TIMEOUT_S = 30


class RegisterError(Exception):
    pass


def register(url: str, credential: str) -> KeyPair:
    """Attaches a new public key to the worker pool of `credential`.

    Args:
        url: the URL of the QFieldCloud API.
        credential: the credential of the worker pool.

    Returns:
        the new key pair of the worker pool.

    Raises:
        RegisterError: if QFieldCloud does not accept the key.
    """
    key_pair = generate_key_pair()

    try:
        response = requests.put(
            f"{url.rstrip('/')}/worker/key/",
            json={"public_key": key_pair.public_key},
            headers={"Authorization": f"WorkerPool {credential}"},
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as err:
        raise RegisterError(f"Cannot reach QFieldCloud: {err}") from err

    if response.status_code == requests.codes.unauthorized:
        raise RegisterError("QFieldCloud rejected the worker pool credential.")

    if response.status_code == requests.codes.conflict:
        raise RegisterError(
            'The worker pool already has a key. To replace it, use "Reset key" in the admin first.'
        )

    if not response.ok:
        raise RegisterError(f"QFieldCloud answered with status {response.status_code}.")

    return key_pair


def main() -> None:
    try:
        key_pair = register(
            os.environ["QFIELDCLOUD_URL"],
            os.environ["QFIELDCLOUD_WORKER_POOL_CREDENTIAL"],
        )
    except KeyError as err:
        sys.exit(f"Missing environment variable {err}.")
    except RegisterError as err:
        sys.exit(str(err))

    print(
        "Registered. Store this with the configuration of all workers of the pool, it is only shown once:",
        file=sys.stderr,
    )
    print(f"QFIELDCLOUD_WORKER_PRIVATE_KEY={key_pair.private_key}")


if __name__ == "__main__":
    main()
