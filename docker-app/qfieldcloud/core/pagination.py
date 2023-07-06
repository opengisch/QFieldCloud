from rest_framework import pagination, response


def parameterize_pagination(cls):
    """
    Set as class attributes the items passed as kwargs.
    """

    def configure_class_object(*args, **kwargs):
        for k, v in kwargs.items():
            setattr(cls, k, v)
        return cls

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
