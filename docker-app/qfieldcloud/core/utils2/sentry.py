import logging
from io import BytesIO, StringIO

import sentry_sdk

logger = logging.getLogger(__name__)


def report_serialization_diff_to_sentry(
    name: str,
    pre_serialization: str,
    post_serialization: str,
    buffer: StringIO,
    body_stream: BytesIO | None,
    capture_message=False,
) -> bool:
    """
    Sends a report to sentry to debug QF-2540. The report includes request information from before and after middleware handle the request as well as a traceback.

    Args:
        pre_serialization: str representing the request `files` keys and meta information before serialization and middleware.
        post_serialization: str representing the request `files` keys and meta information after serialization and middleware.
        buffer: StringIO buffer from which to extract traceback capturing callstack ahead of the calling function.
        bodystream: BytesIO buffer capturing the request's raw body.
        capture_message: bool used as a flag by the caller to create an extra event against Sentry to attach the files to.
    """
    with sentry_sdk.configure_scope() as scope:
        try:
            logger.info("Sending explicit sentry report!")

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

            if body_stream:
                filename = f"{name}_rawbody.txt"
                scope.add_attachment(bytes=body_stream.getvalue(), filename=filename)

            if capture_message:
                sentry_sdk.capture_message("Explicit Sentry report!", scope=scope)

            return True

        except Exception as error:
            logger.error(f"Unable to send file to Sentry: failed on {error}")
            sentry_sdk.capture_exception(error)
            return False
