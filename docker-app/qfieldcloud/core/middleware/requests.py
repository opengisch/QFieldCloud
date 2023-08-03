import io
import shutil


def attach_keys(get_response):
    """
    QF-2540
    Annotate request with a str representation of relevant fields, so as to obtain a diff
    by comparing with the post-serialized request later in the callstack.
    """

    def middleware(request):
        input_stream = io.BufferedReader(io.BytesIO(request.body))

        request_attributes = {
            "file_key": str(request.FILES.keys()),
            "meta": str(request.META),
        }

        # only report rawbody of less-than-10MBs multipart requests
        if (
            "multipart/form-data;boundary" in request.headers["Content-Type"]
            and input_stream.tell() < 10000000
        ):
            output_stream = io.BytesIO()
            shutil.copyfileobj(input_stream, output_stream)
            request.body_stream = output_stream

        if "file" in request.FILES.keys():
            request_attributes["files"] = request.FILES.getlist("file")

        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
