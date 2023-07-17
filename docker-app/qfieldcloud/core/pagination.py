from itertools import islice
from typing import Callable

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

    pagination_controls_in_response = False

    def get_headers(self) -> dict[str, int]:
        """
        Initializes a new header field to carry the number of paginated entries
        if the class method `count_entries` is `True`.
        """
        return {"X-Total-Count": self.count}

    def get_paginated_response(self, data) -> response.Response:
        """
        When `pagination_controls_in_response` is False,
        sets the header field initialized in the previous method to the number of paginated entries
        and return just the entries in the response body, slicing them to never exceed `settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT`.
        When it's true, return the original payload with navigation controls.
        """
        if self.request.GET.get("offset") and not self.request.GET.get("limit"):
            payload = islice(data, settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT)

        if self.pagination_controls_in_response:
            payload = {
                "results": data,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "count": self.count,
            }
            return response.Response(payload)
        else:
            return response.Response(payload, headers=self.get_headers())
