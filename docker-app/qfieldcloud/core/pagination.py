from rest_framework import pagination, response


class LimitOffsetPagination(pagination.LimitOffsetPagination):
    """
    Blank implementation defining:
        - response.data["count"]
        - response.data["next"]
        - response.data["previous"]
        - response.data.["results"]
    """


class LimitOffsetPaginationResults(pagination.LimitOffsetPagination):
    """Custom implemention such that response.data = response.data.results"""

    def get_paginated_response(self, data) -> response.Response:
        return response.Response(data)
