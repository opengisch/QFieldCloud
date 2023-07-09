from typing import Callable

from qfieldcloud.settings import QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT
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
    Custom implementation such that response.data = (DRF's blanket LimitOffsetPagination response).data.results
    Optionally sets a new header ('X-Total-Count') to the number of entries in the paginated response.
    Use it only if you can afford the performance cost.
    Can be customized when assigning 'pagination_class'.
    """

    default_limit = QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT

    def get_headers(self) -> dict[str, None]:
        """Initializes a new header field to carry the number of paginated entries."""
        return {"X-Total-Count": None}

    def get_paginated_response(self, data) -> response.Response:
        """
        Sets the header field initialized in the previous method to the number of paginated entries.
        Return just the entries in the response body.
        """
        if self.count_entries:
            headers = self.get_headers()
            headers["X-Total-Count"] = len(data)
            return response.Response(data, headers=headers)
        else:
            return response.Response(data)
