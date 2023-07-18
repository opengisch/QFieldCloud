from itertools import islice
from typing import Any, Callable

from django.conf import settings
from rest_framework import pagination, response


def parameterize_pagination(_class: type) -> Callable:
    """
    Set as class attributes the items passed as kwargs.
    """

    def configure_class_object(*args, **kwargs) -> type:
        for k, v in kwargs.items():
            setattr(_class, k, v)
        return _class

    return configure_class_object


@parameterize_pagination
class QfcLimitOffsetPagination(pagination.LimitOffsetPagination):
    """
    Based on LimitOffsetPagination.
    Custom implementation such that `response.data = LimitOffsetPagination.data.results` from DRF's blanket implementation.
    Optionally sets a new header `X-Total-Count` to the number of entries in the paginated response.
    Use it only if you can afford the performance cost.
    Can be customized when assigning `pagination_class`.
    """

    def get_headers(self) -> dict[str, Any]:
        """
        Initializes a new header field to carry the pagination controls.
        """
        headers = {"X-Total-Count": self.count}

        next_link = self.get_next_link()
        if next_link:
            headers["X-Next"] = next_link

        previous_link = self.get_previous_link()
        if previous_link:
            headers["X-Previous"] = previous_link

        return headers

    def get_paginated_response(self, data) -> response.Response:
        """
        When `pagination_controls_in_response` is False
        and when the user didn't ask for pagination controls in the request with the `pagination_controls: True` parameter,
        sets the header field initialized in the previous method to the number of paginated entries and return just the entries in the response body,
        slicing them to never exceed `settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT`.
        Otherwise return the original payload with navigation controls.
        """
        if self.request.GET.get("offset") and not self.request.GET.get("limit"):
            # slice serialized data to enforce the application wide limit
            data = islice(data, settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT)

        # return only results, injecting pagination controls into headers
        return response.Response(data, headers=self.get_headers())
