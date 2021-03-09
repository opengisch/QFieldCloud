from django.core import exceptions
from qfieldcloud.core import exceptions as qfieldcloud_exceptions
from rest_framework import exceptions as rest_exceptions
from rest_framework.response import Response


def exception_handler(exc, context):

    if isinstance(exc, qfieldcloud_exceptions.QFieldCloudException):
        pass
    elif isinstance(exc, rest_exceptions.APIException):
        exc = qfieldcloud_exceptions.APIError(
            status_code=exc.status_code, detail=exc.detail
        )
    elif isinstance(exc, exceptions.ObjectDoesNotExist):
        exc = qfieldcloud_exceptions.ObjectNotFoundError(detail=str(exc))
    elif isinstance(exc, exceptions.ValidationError):
        exc = qfieldcloud_exceptions.ValidationError(detail=str(exc))
    else:
        exc = qfieldcloud_exceptions.QFieldCloudException(detail=str(exc))

    body = {
        "code": exc.code,
        "message": exc.message,
        "debug": {
            "view": str(context["view"]),
            "args": context["args"],
            "kwargs": context["kwargs"],
            "request": str(context["request"]),
            "detail": exc.detail,
        },
    }

    return Response(
        body,
        status=exc.status_code,
    )
