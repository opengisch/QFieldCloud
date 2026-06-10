from collections.abc import Callable

from constance import config
from django.http import HttpRequest, HttpResponse
from django.test.utils import override_settings


class DynamicMaxNumberFieldsLimitMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Dynamically set the DATA_UPLOAD_MAX_NUMBER_FIELDS setting limit based on the Constance value."""
        with override_settings(
            DATA_UPLOAD_MAX_NUMBER_FIELDS=config.WEB_DATA_UPLOAD_MAX_NUMBER_FIELDS
        ):
            return self.get_response(request)
