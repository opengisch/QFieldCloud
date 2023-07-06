from rest_framework import pagination, response


def parameterize_pagination(_class: type):
    """
    Set as class attributes the items passed as kwargs.
    """

    def configure_class_object(*args, **kwargs) -> type:
        for k, v in kwargs.items():
            setattr(_class, k, v)
        return _class

    return configure_class_object


@parameterize_pagination
class PaginateResults(pagination.LimitOffsetPagination):
    """
    Based on LimitOffsetPagination. Custom implementation such that response.data = (DRF's blanket LimitOffsetPagination response).data.results
    For comparison, the DRF's blanket implementation defines:
    - response.data["results"]
    - response.data["count"]
    - response.data["next"]
    - response.data["previous"]
    """

    def get_paginated_response(self, data) -> response.Response:
        return response.Response(data)
