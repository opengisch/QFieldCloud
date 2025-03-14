from typing import Any, Callable

from django.http.request import HttpRequest
from django.http.response import HttpResponse, HttpResponseForbidden

from qfieldcloud.core import permissions_utils


def permission_check(perm: str, check_args: list[str | Callable] = []) -> Callable:
    perm_check = getattr(permissions_utils, perm)

    def decorator_wrapper(func: Callable):
        def decorator(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            parsed_check_args = []

            for arg in check_args:
                if callable(arg):
                    parsed_check_args.append(arg(request))
                else:
                    parsed_check_args.append(getattr(request, arg))

            is_permitted = perm_check(request.user, *parsed_check_args)

            if is_permitted:
                return func(request, *args, **kwargs)
            else:
                return HttpResponseForbidden()

        return decorator

    return decorator_wrapper
