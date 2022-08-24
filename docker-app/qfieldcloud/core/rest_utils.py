import logging

from django.conf import settings
from django.core import exceptions
from qfieldcloud.core import exceptions as qfieldcloud_exceptions
from rest_framework import exceptions as rest_exceptions
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def exception_handler(exc, context):

    # Map exceptions to qfc exceptions
    is_error = False
    if isinstance(exc, rest_exceptions.AuthenticationFailed):
        qfc_exc = qfieldcloud_exceptions.AuthenticationFailedError()
    elif isinstance(exc, rest_exceptions.NotAuthenticated):
        qfc_exc = qfieldcloud_exceptions.NotAuthenticatedError()
    elif isinstance(exc, rest_exceptions.PermissionDenied):
        qfc_exc = qfieldcloud_exceptions.PermissionDeniedError()
    elif isinstance(exc, exceptions.ObjectDoesNotExist):
        qfc_exc = qfieldcloud_exceptions.ObjectNotFoundError(detail=str(exc))
    elif isinstance(exc, exceptions.ValidationError):
        qfc_exc = qfieldcloud_exceptions.ValidationError(detail=str(exc))
    elif isinstance(exc, qfieldcloud_exceptions.QFieldCloudException):
        is_error = True
        qfc_exc = exc
    elif isinstance(exc, rest_exceptions.APIException):
        is_error = True
        qfc_exc = qfieldcloud_exceptions.APIError(exc.detail, exc.status_code)
    else:
        # Unexpected ! We rethrow original exception to make debugging tests easier
        if settings.IN_TEST_SUITE:
            raise exc
        is_error = True
        qfc_exc = qfieldcloud_exceptions.QFieldCloudException(detail=str(exc))

    if is_error:
        # log the original exception
        logging.exception(exc)
    else:
        # log as info as repeated errors could still indicate an actual issue
        logging.info(str(exc))

    body = {
        "code": qfc_exc.code,
        "message": qfc_exc.message,
    }

    if settings.DEBUG:
        body["debug"] = {
            "view": str(context["view"]),
            "args": context["args"],
            "kwargs": context["kwargs"],
            "request": str(context["request"]),
            "detail": qfc_exc.detail,
        }

    return Response(
        body,
        status=qfc_exc.status_code,
    )
