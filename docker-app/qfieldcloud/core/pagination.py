from rest_framework import pagination, response


def parameterize_pagination(cls):
    def capture_args(*args, **kwargs):
        user_custom_default_limit = kwargs.get("default_limit", None)

        if user_custom_default_limit:
            cls.default_limit = user_custom_default_limit

        return cls

    return capture_args


@parameterize_pagination
class PaginateResults(pagination.LimitOffsetPagination):
    """
    Custom implementation such that response.data = (DRF blanket implementation's response).data.results
    For comparison, the DRF's blanket implementation defines:
    - response.data.["results"]
    - response.data["count"]
    - response.data["next"]
    - response.data["previous"]
    """

    def get_paginated_response(self, data) -> response.Response:
        return response.Response(data)
