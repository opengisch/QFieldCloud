import os

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import MiddlewareNotUsed


class TestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        if os.environ.get("ENVIRONMENT") != "test":
            raise MiddlewareNotUsed()

    def __call__(self, request):
        ContentType.objects.clear_cache()
        return self.get_response(request)
