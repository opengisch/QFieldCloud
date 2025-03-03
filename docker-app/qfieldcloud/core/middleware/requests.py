import io
import logging
import shutil

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
        # add a copy of the request body to the request
        if (
            settings.SENTRY_DSN
            and request.method == "POST"
            and "Content-Length" in request.headers
            and (
                int(request.headers["Content-Length"])
                < int(config.SENTRY_REQUEST_MAX_SIZE_TO_SEND)
            )
        ):
            logger.info("Making a temporary copy for request body.")

            input_stream = io.BytesIO(request.body)
            output_stream = io.BytesIO()
            shutil.copyfileobj(input_stream, output_stream)
            request.body_stream = output_stream

        request_attributes = {
            "file_key": str(request.FILES.keys()),
            "meta": str(request.META),
            "files": request.FILES.getlist("file"),
        }
        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
