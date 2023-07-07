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
    Based on LimitOffsetPagination. Custom implementation such that response.data = (DRF's blanket LimitOffsetPagination response).data.results
    For comparison, the DRF's blanket implementation defines:
    - response.data["results"]
    - response.data["count"]
    - response.data["next"]
    - response.data["previous"]
    which are not available from instances of the present class.
    """

    default_limit = QFIELDCLOUD_API_DEFAULT_PAGE_LIMIT

    def get_paginated_response(self, data) -> response.Response:
        return response.Response(data)
