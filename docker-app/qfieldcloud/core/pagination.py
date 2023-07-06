from rest_framework import pagination, response


class LimitOffsetPaginationResults(pagination.LimitOffsetPagination):
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
