import atexit
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Callable, Dict, List, Optional, Union

from qgis.core import Qgis, QgsApplication, QgsMapLayer, QgsProviderRegistry
from qgis.PyQt import QtCore

qgs_stderr_logger = logging.getLogger("QGIS_STDERR")
qgs_stderr_logger.setLevel(logging.DEBUG)
qgs_msglog_logger = logging.getLogger("QGIS_MSGLOG")
qgs_msglog_logger.setLevel(logging.DEBUG)


def _qt_message_handler(mode, context, message):
    log_level = logging.DEBUG
    if mode == QtCore.QtDebugMsg:
        log_level = logging.DEBUG
    elif mode == QtCore.QtInfoMsg:
        log_level = logging.INFO
    elif mode == QtCore.QtWarningMsg:
        log_level = logging.WARNING
    elif mode == QtCore.QtCriticalMsg:
        log_level = logging.CRITICAL
    elif mode == QtCore.QtFatalMsg:
        log_level = logging.FATAL

    qgs_stderr_logger.log(
        log_level,
        message,
        extra={
            "time": datetime.now().isoformat(),
            "line": context.line,
            "file": context.file,
            "function": context.function,
        },
    )


QtCore.qInstallMessageHandler(_qt_message_handler)


def _write_log_message(message, tag, level):
    log_level = logging.DEBUG

    # in 3.16 it was Qgis.None, but since None is a reserved keyword, it was inaccessible
    try:
        Qgis.NoLevel
    except Exception:
        Qgis.NoLevel = 4

    if level == Qgis.NoLevel:
        log_level = logging.DEBUG
    elif level == Qgis.Info:
        log_level = logging.INFO
    elif level == Qgis.Success:
        log_level = logging.INFO
    elif level == Qgis.Warning:
        log_level = logging.WARNING
    elif level == Qgis.Critical:
        log_level = logging.CRITICAL

    qgs_msglog_logger.log(
        log_level,
        message,
        extra={
            "time": datetime.now().isoformat(),
            "tag": tag,
        },
    )


QGISAPP: QgsApplication = None


def start_app():
    """
    Will start a QgsApplication and call all initialization code like
    registering the providers and other infrastructure. It will not load
    any plugins.

    You can always get the reference to a running app by calling `QgsApplication.instance()`.

    The initialization will only happen once, so it is safe to call this method repeatedly.

        Returns
        -------
        QgsApplication

        A QgsApplication singleton
    """
    global QGISAPP

    if QGISAPP is None:
        qgs_stderr_logger.info("Starting QGIS app...")
        argvb = []

        # Note: QGIS_PREFIX_PATH is evaluated in QgsApplication -
        # no need to mess with it here.
        gui_flag = False
        QGISAPP = QgsApplication(argvb, gui_flag)

        QtCore.qInstallMessageHandler(_qt_message_handler)
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp(
            "", "QGIS-PythonTestConfigPath"
        )
        QGISAPP.initQgis()

        QtCore.qInstallMessageHandler(_qt_message_handler)
        QgsApplication.messageLog().messageReceived.connect(_write_log_message)

        @atexit.register
        def exitQgis():
            stop_app()

    return QGISAPP


def stop_app():
    """
    Cleans up and exits QGIS
    """
    global QGISAPP

    QGISAPP.exitQgis()
    del QGISAPP


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
