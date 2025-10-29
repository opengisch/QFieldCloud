from typing import Any

from allauth.account.utils import get_adapter
from django.http import HttpRequest


def signup_open(request: HttpRequest) -> dict[str, Any]:
    adapter = get_adapter()

    return {
        "is_signup_open": adapter.is_open_for_signup(request),
    }
