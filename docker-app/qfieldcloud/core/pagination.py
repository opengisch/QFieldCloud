from rest_framework import pagination, response


class LimitOffsetPaginationResults(pagination.LimitOffsetPagination):
    """
    Custom implemention such that response.data = response.data.results
    For comparison, the DRF's blank implementation defines:
    - response.data["count"]
    - response.data["next"]
    - response.data["previous"]
    - response.data.["results"]"""

    def get_paginated_response(self, data) -> response.Response:
        return response.Response(data)
