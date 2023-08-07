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
        # only report raw body of POST requests with a < 10MBs content length
        if (
            request.method == "POST"
            and "Content-Length" in request.headers
            and int(request.headers["Content-Length"]) < 10000000
        ):
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
