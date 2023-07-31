import copy

from django.http import HttpRequest, HttpResponse


def attach_keys(get_response):
    """
    QF-2540
    Annotate request with a str representation of relevant fields, so as to obtain a diff
    by comparing with the post-serialized request later in the callstack.
    """

    def middleware(request: HttpRequest) -> HttpResponse:
        request_attributes = {
            "meta": str(request.META),
            "files": str(request.FILES),
        }
        if hasattr(request, "POST"):
            copied_body = copy.copy(
                request.body
            )  # not copying would exhaust the data, raising at serialization
            request_attributes["body"] = str(copied_body)
        request.attached_keys = str(request_attributes)
        response = get_response(request)
        return response

    return middleware
