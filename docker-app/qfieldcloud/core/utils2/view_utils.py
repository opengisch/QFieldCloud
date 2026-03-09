from typing import Any

from django.http import Http404, HttpRequest


def blocked_view(request: HttpRequest, *args: Any, **kwargs: Any) -> None:
    raise Http404
