import logging

from django.conf import settings
from django.core import exceptions
from qfieldcloud.core import exceptions as qfieldcloud_exceptions
from rest_framework import exceptions as rest_exceptions
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def exception_handler(exc, context):

    if isinstance(exc, qfieldcloud_exceptions.QFieldCloudException):
        pass
    elif isinstance(exc, rest_exceptions.AuthenticationFailed):
        exc = qfieldcloud_exceptions.AuthenticationFailedError()
    elif isinstance(exc, rest_exceptions.NotAuthenticated):
        exc = qfieldcloud_exceptions.NotAuthenticatedError()
    elif isinstance(exc, rest_exceptions.APIException):
        exc = qfieldcloud_exceptions.APIError(
            status_code=exc.status_code, detail=exc.detail
        )
    elif isinstance(exc, exceptions.ObjectDoesNotExist):
        exc = qfieldcloud_exceptions.ObjectNotFoundError(detail=str(exc))
    elif isinstance(exc, exceptions.ValidationError):
        exc = qfieldcloud_exceptions.ValidationError(detail=str(exc))
    else:
        # When running tests, we rethrow the exception, so we get a full trace to
        # help with debugging
        if settings.IN_TEST_SUITE:
            raise exc
        logging.exception(exc)
        exc = qfieldcloud_exceptions.QFieldCloudException(detail=str(exc))

    body = {
        "code": exc.code,
        "message": exc.message,
    }

    if settings.DEBUG:
        body["debug"] = {
            "view": str(context["view"]),
            "args": context["args"],
            "kwargs": context["kwargs"],
            "request": str(context["request"]),
            "detail": exc.detail,
        }

    logging.info(exc)

    return Response(
        body,
        status=exc.status_code,
    )
