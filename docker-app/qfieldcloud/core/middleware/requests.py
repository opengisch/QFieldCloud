import io
import shutil


def attach_keys(get_response):
    """
    QF-2540
    Annotate request with:
    - a `str` representation of relevant fields, so as to obtain a diff by comparing with the post-serialized request later in the callstack;
    - a byte-for-byte, non stealing copy of the raw body to inspect multipart boundaries.
    """

    def middleware(request):
        input_stream = io.BytesIO(request.body)

        request_attributes = {
            "file_key": str(request.FILES.keys()),
            "meta": str(request.META),
        }

        # only report raw body of POST requests with a < 10MBs content length
        if (
            request.META["REQUEST_METHOD"] == "POST"
            and int(request.META["CONTENT_LENGTH"]) < 10000000
        ):
            output_stream = io.BytesIO()
            shutil.copyfileobj(input_stream, output_stream)
            request.body_stream = output_stream
            request_attributes["files"] = request.FILES.getlist("file")

        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
