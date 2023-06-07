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
        if "file" in request.FILES.keys():
            request_attributes["files"] = request.FILES.getlist("file")
        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
