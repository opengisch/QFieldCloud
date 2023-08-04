import io
import shutil


def attach_keys(get_response):
    """
    QF-2540
    Annotate request with a str representation of relevant fields, so as to obtain a diff
    by comparing with the post-serialized request later in the callstack.
    """

    def middleware(request):
        request_attributes = {
            "file_key": str(request.FILES.keys()),
            "meta": str(request.META),
        }

        content_type = request.headers.get("Content-Type") or request.headers.get(
            "content-type"
        )

        # only report raw body multipart requests
        if (
            content_type
            and "multipart/form-data;boundary" in content_type
        ):
            request_attributes["content_type"] = content_type
            input_stream = io.BytesIO(request.body)
            output_stream = io.BytesIO()
            shutil.copyfileobj(input_stream, output_stream)
            request.body_stream = output_stream

        if "file" in request.FILES.keys():
            request_attributes["files"] = request.FILES.getlist("file")

        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
