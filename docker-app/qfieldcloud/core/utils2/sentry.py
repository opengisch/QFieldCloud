import logging
from io import StringIO

import sentry_sdk

logger = logging.getLogger(__name__)


def report_serialization_diff_to_sentry(
    name: str, pre_serialization: str, post_serialization: str, buffer: StringIO
):
    """
    Sends a report to sentry to debug QF-2540. The report includes request information from before and after middleware handle the request as well as a traceback.

    Args:
        pre_serialization: str representing the request `files` keys and meta information before serialization and middleware.
        post_serialization: str representing the request `files` keys and meta information after serialization and middleware.
        buffer: StringIO buffer from which to extract traceback capturing callstack ahead of the calling function.
    """

    traceback = bytes(buffer.getvalue(), encoding="utf-8")
    report = f"Pre:\n{pre_serialization}\n\nPost:{post_serialization}"

    with sentry_sdk.configure_scope() as scope:
        try:
            filename = f"{name}_contents.txt"
            scope.add_attachment(bytes=bytes(report), filename=filename)

            filename = f"{name}_traceback.txt"
            scope.add_attachment(
                bytes=traceback,
                filename=filename,
            )
        except Exception as error:
            sentry_sdk.capture_exception(error)
            logging.error(f"Unable to send file to Sentry: failed on {error}")
