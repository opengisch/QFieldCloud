import io
import logging
import shutil
import time

from constance import config
from django.conf import settings

logger = logging.getLogger(__name__)


def attach_keys(get_response):
    """
    QF-2540
    Annotate request with:
    - a `str` representation of relevant fields, so as to obtain a diff by comparing with the post-serialized request later in the callstack;
    - a byte-for-byte, non stealing copy of the raw body to inspect multipart boundaries.
    """

    def middleware(request):
        middleware_start_time = None

        # Log when middleware runs (after multipart parsing completes)
        if request.method == "POST" and "/api/v1/files/" in request.path:
            content_length = request.META.get("CONTENT_LENGTH", "unknown")
            middleware_start_time = time.time()

            logger.info(
                f"[UPLOAD_DEBUG] Middleware started - "
                f"Path: {request.path}, Content-Length: {content_length}, "
                f"Time: {middleware_start_time}"
            )

            # Check if files are already parsed
            try:
                if hasattr(request, "FILES"):
                    files_count = len(request.FILES)
                    files_keys = list(request.FILES.keys())
                else:
                    files_count = 0
                    files_keys = []
                logger.info(
                    f"[UPLOAD_DEBUG] Files parsed - "
                    f"FILES count: {files_count}, FILES keys: {files_keys}"
                )
            except Exception as e:
                logger.warning(
                    f"[UPLOAD_DEBUG] Error accessing FILES - "
                    f"Error: {e}"
                )

        # add a copy of the request body to the request
        if (
            settings.SENTRY_DSN
            and request.method == "POST"
            and "Content-Length" in request.headers
        ):
            if (
                int(request.headers["Content-Length"])
                < int(config.SENTRY_REQUEST_MAX_SIZE_TO_SEND)
            ):
                logger.info("Making a temporary copy for request body.")

                input_stream = io.BytesIO(request.body)
                output_stream = io.BytesIO()
                shutil.copyfileobj(input_stream, output_stream)
                request.body_stream = output_stream

        request_attributes = {
            "file_key": str(request.FILES.keys()) if hasattr(request, "FILES") else "[]",
            "meta": str(request.META),
            "files": request.FILES.getlist("file") if hasattr(request, "FILES") else [],
        }
        request.attached_keys = str(request_attributes)

        # Store middleware start time for later comparison
        if middleware_start_time is not None:
            request._middleware_start_time = middleware_start_time

        response = get_response(request)

        # Log when middleware completes
        if middleware_start_time is not None:
            middleware_end_time = time.time()
            middleware_duration = middleware_end_time - middleware_start_time
            logger.info(
                f"[UPLOAD_DEBUG] Middleware completed - "
                f"Duration: {middleware_duration:.2f}s, Status: {response.status_code}"
            )

        return response

    return middleware
