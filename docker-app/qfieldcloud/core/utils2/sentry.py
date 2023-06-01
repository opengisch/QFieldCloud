import logging
from io import StringIO

from sentry_sdk import configure_scope

logger = logging.getLogger(__name__)


def report_to_sentry(
    name: str, pre_serialization: str, post_serialization: str, buffer: StringIO
):
    """
    QF-2540
    Send the report to Sentry
    """

    traceback = bytes(buffer.getvalue(), encoding="utf-8")
    report = f"Pre:\n{pre_serialization}\n\nPost:{post_serialization}"

    with configure_scope() as scope:
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
