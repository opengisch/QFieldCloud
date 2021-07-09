import socket
import subprocess
import sys
import uuid
from contextlib import contextmanager
from typing import Callable, List, Optional

from qgis.core import QgsMapLayer, QgsProviderRegistry


class Step:
    def __init__(
        self,
        name: str,
        method: Callable,
        arg_names: List[str] = [],
        return_names: List[str] = [],
        output_names: List[str] = [],
        public_returns: List[str] = [],
    ):
        self.name = name
        self.method = method
        self.arg_names = arg_names
        # names of method return values
        self.return_names = return_names
        # names of method return values that will be part of the outputs
        self.output_names = output_names
        # names of method return values that will be available in arg_names for the next steps
        self.public_returns = public_returns
        self.stage = 0
        self.outputs = {}


class BaseException(Exception):
    """QFieldCloud Exception"""

    message = ""

    def __init__(self, message: str = None, **kwargs):
        self.message = (message or self.message) % kwargs
        self.details = kwargs

        super().__init__(self.message)


@contextmanager
def logger_context(step: Step):
    log_uuid = uuid.uuid4()

    try:
        # NOTE we are still using the reference from the `steps` list
        step.stage = 1
        print(f"::<<<::{log_uuid} {step.name}", file=sys.stderr)
        yield
        step.stage = 2
    finally:
        print(f"::>>>::{log_uuid}", file=sys.stderr)


def is_localhost(hostname: str, port: int = None) -> bool:
    """returns True if the hostname points to the localhost, otherwise False."""
    if port is None:
        port = 22  # no port specified, lets just use the ssh port
    hostname = socket.getfqdn(hostname)
    if hostname in ("localhost", "0.0.0.0"):
        return True
    localhost = socket.gethostname()
    localaddrs = socket.getaddrinfo(localhost, port)
    targetaddrs = socket.getaddrinfo(hostname, port)
    for (_family, _socktype, _proto, _canonname, sockaddr) in localaddrs:
        for (_rfamily, _rsocktype, _rproto, _rcanonname, rsockaddr) in targetaddrs:
            if rsockaddr[0] == sockaddr[0]:
                return True
    return False


def has_ping(hostname: str) -> bool:
    ping = subprocess.Popen(
        ["ping", "-c", "1", "-w", "5", hostname],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    out, error = ping.communicate()

    return not bool(error) and "100% packet loss" not in out.decode("utf8")


def get_layer_filename(layer: QgsMapLayer) -> Optional[str]:
    metadata = QgsProviderRegistry.instance().providerMetadata(
        layer.dataProvider().name()
    )

    if metadata is not None:
        decoded = metadata.decodeUri(layer.source())
        if "path" in decoded:
            return decoded["path"]

    return None
