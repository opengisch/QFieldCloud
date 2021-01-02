import json

from django.core import exceptions

from rest_framework import status
from rest_framework import exceptions as rest_exceptions
from rest_framework.response import Response

from rest_framework.exceptions import ErrorDetail
from rest_framework.views import exception_handler as rest_exception_handler

from qfieldcloud.core.models import (
    Project, Delta)

from qfieldcloud.core import exceptions as qfieldcloud_exceptions


def exception_handler(exc, context):

    status_code = None
    message = None
    code = None

    if isinstance(exc, qfieldcloud_exceptions.QFieldCloudException):
        pass
    elif isinstance(exc, rest_exceptions.APIException):
        exc = qfieldcloud_exceptions.APIError(
            status_code=exc.status_code,
            message=exc.detail)
    elif isinstance(exc, exceptions.ObjectDoesNotExist):
        exc = qfieldcloud_exceptions.ObjectNotFoundError(message=str(exc))
    elif isinstance(exc, exceptions.ValidationError):
        exc = qfieldcloud_exceptions.ValidationError(message=str(exc))
    else:
        exc = qfieldcloud_exceptions.QFieldCloudException(
            message=str(exc))

    code = exc.code
    status_code = exc.status_code
    message = exc.message

    body = {
        'code': code,
        'message': message,
        'debug': {
            'view': str(context['view']),
            'args': context['args'],
            'kwargs': context['kwargs'],
            'request': str(context['request']),
        },
    }

    return Response(body, status=status_code,)
