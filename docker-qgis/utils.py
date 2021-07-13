import json
import socket
import subprocess
import sys
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Optional, Union

from qgis.core import QgsMapLayer, QgsProviderRegistry


class Step:
    def __init__(
        self,
        name: str,
        method: Callable,
        arguments: Dict[str, Any] = {},
        arg_names: List[str] = [],
        return_names: List[str] = [],
        output_names: List[str] = [],
        public_returns: List[str] = [],
    ):
        self.name = name
        self.method = method
        self.arguments = arguments
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


def run_task(
    steps: List[Step],
    feedback_filename: Optional[Union[IO, Path]],
) -> Dict:
    """Executes the steps required to run a task and return structured feedback from the execution

    Each step has a method that is executed.
    Method may take arguments as defined in `arguments` and ordered in `arg_names`.
    Method may return values, as defined in `return_values`.
    Some return values can used as task output, as defined in `output_names`.
    Some return values can used as arguments for next steps, as defined in `public_returns`.

    Args:
        steps (List[Step]): ordered steps to be executed
        feedback_filename (Optional[Union[IO, Path]]): write feedback to an IO device, to Path filename, or don't write it
    """
    feedback = {}
    # it may be modified after the successful completion of each step.
    returned_arguments = {}

    try:
        for step in steps:
            with logger_context(step):
                arguments = {
                    **returned_arguments,
                    **step.arguments,
                }
                args = [arguments[arg_name] for arg_name in step.arg_names]
                return_values = step.method(*args)
                return_values = (
                    return_values if len(step.return_names) > 1 else (return_values,)
                )

                return_map = {}
                for name, value in zip(step.return_names, return_values):
                    return_map[name] = value

                for output_name in step.output_names:
                    step.outputs[output_name] = return_map[output_name]

                for return_name in step.public_returns:
                    returned_arguments[return_name] = return_map[return_name]

    except Exception as err:
        feedback["error"] = str(err)
        (_type, _value, tb) = sys.exc_info()
        feedback["error_stack"] = traceback.format_tb(tb)
    finally:
        feedback["steps"] = [
            {
                "name": step.name,
                "stage": step.stage,
                "outputs": step.outputs,
            }
            for step in steps
        ]

        if feedback_filename in [sys.stderr, sys.stdout]:
            print("Feedback:")
            print(json.dump(feedback, feedback_filename, indent=2, sort_keys=True))
        elif isinstance(feedback_filename, Path):
            with open(feedback_filename, "w") as f:
                json.dump(feedback, f, indent=2, sort_keys=True)

        return feedback
