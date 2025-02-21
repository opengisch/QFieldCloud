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
    Inject pagination controls and counter into the response headers.
    Can be customized when assigning `pagination_class`.
    """

    def get_headers(self) -> dict[str, Any]:
        """
        Set new header fields to carry pagination controls.
        """
        headers = {
            "X-Total-Count": str(self.count),
        }

        next_link: str | None = self.get_next_link()

        if next_link:
            headers["X-Next-Page"] = next_link

        previous_link: str | None = self.get_previous_link()
        if previous_link:
            headers["X-Previous-Page"] = previous_link

        return headers

    def get_paginated_response(self, data) -> response.Response:
        """
        Paginate results injecting pagination controls and counter into response headers.
        """
        if (
            self.request is not None
            and self.request.GET.get("offset")
            and not self.request.GET.get("limit")
        ):
            # slice serialized data to enforce the application wide limit
            data = islice(data, settings.QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT)

        return response.Response(data, headers=self.get_headers())

    def get_paginated_response_schema(self, schema) -> dict[str, Any]:
        """Overrides schema with just the results"""
        return schema
