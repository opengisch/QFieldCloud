import logging
from io import StringIO

import sentry_sdk

logger = logging.getLogger(__name__)


def report_serialization_diff_to_sentry(
    name: str,
    pre_serialization: str,
    post_serialization: str,
    buffer: StringIO,
    capture_message=False,
) -> bool:
    """
    Sends a report to sentry to debug QF-2540. The report includes request information from before and after middleware handle the request as well as a traceback.

    Args:
        pre_serialization: str representing the request `files` keys and meta information before serialization and middleware.
        post_serialization: str representing the request `files` keys and meta information after serialization and middleware.
        buffer: StringIO buffer from which to extract traceback capturing callstack ahead of the calling function.
        capture_message: bool used as a flag by the caller to create an extra event against Sentry to attach the files to.
    """
    with sentry_sdk.configure_scope() as scope:
        try:
            filename = f"{name}_contents.txt"
            scope.add_attachment(
                bytes=bytes(
                    f"Pre:\n{pre_serialization}\n\nPost:{post_serialization}",
                    encoding="utf8",
                ),
                filename=filename,
            )

            filename = f"{name}_traceback.txt"
            scope.add_attachment(
                bytes=bytes(buffer.getvalue(), encoding="utf8"),
                filename=filename,
            )
            if capture_message:
                sentry_sdk.capture_message("Sending to Sentry...", scope=scope)
            return True
        except Exception as error:
            sentry_sdk.capture_exception(error)
            logging.error(f"Unable to send file to Sentry: failed on {error}")
            return False
