from typing import Any

from allauth.account.utils import get_adapter
from django.http import Http404, HttpRequest
from django.urls import reverse


def blocked_view(request: HttpRequest, *args: Any, **kwargs: Any) -> None:
    raise Http404


def get_signup_url(request: HttpRequest) -> str | None:
    """
    Get the signup url if the adapter is open to signup, else return None.
    """
    adapter = get_adapter()

    if adapter.is_open_for_signup(request):
        return request.build_absolute_uri(reverse("account_signup"))
    else:
        return None
