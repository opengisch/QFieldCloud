import logging

from django.conf import settings
from django.core import exceptions
from django.http import Http404
from rest_framework import exceptions as rest_exceptions
from rest_framework.response import Response

from qfieldcloud.core import exceptions as qfieldcloud_exceptions

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    # Map exceptions to qfc exceptions
    if isinstance(exc, rest_exceptions.AuthenticationFailed):
        qfc_exc = qfieldcloud_exceptions.AuthenticationFailedError()
    elif isinstance(exc, rest_exceptions.NotAuthenticated):
        qfc_exc = qfieldcloud_exceptions.NotAuthenticatedError()
    elif isinstance(exc, rest_exceptions.PermissionDenied):
        qfc_exc = qfieldcloud_exceptions.PermissionDeniedError()
    elif isinstance(exc, (exceptions.ObjectDoesNotExist, Http404)):
        qfc_exc = qfieldcloud_exceptions.ObjectNotFoundError(detail=str(exc))
    elif isinstance(exc, exceptions.ValidationError):
        qfc_exc = qfieldcloud_exceptions.ValidationError(detail=str(exc))
    elif isinstance(exc, qfieldcloud_exceptions.QFieldCloudException):
        qfc_exc = exc
    elif isinstance(exc, rest_exceptions.APIException):
        # Map DRF API exceptions to qfc exceptions.
        # NOTE the `detail` attribute is always present on `APIException` but it is not properly typed,
        # so we use the `getattr` trick without a third argument to fix typing, but still raise an exception if the attribute is not present.
        qfc_exc = qfieldcloud_exceptions.APIError(
            detail=getattr(exc, "detail"),
            status_code=exc.status_code,
        )
    else:
        # Unexpected ! We rethrow original exception to make debugging tests easier
        if settings.IN_TEST_SUITE:
            raise exc

        qfc_exc = qfieldcloud_exceptions.QFieldCloudException(detail=str(exc))

    # Log level is defined by the exception
    if qfc_exc.log_as_error:
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
