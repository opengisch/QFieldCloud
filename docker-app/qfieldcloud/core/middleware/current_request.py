import contextvars
import logging
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import TYPE_CHECKING, Any

from django.core.cache.backends.base import BaseCache
from django.core.cache.backends.locmem import LocMemCache
from django.http import HttpRequest

# marker for separating args from kwargs (needs to be global)
cache_args_kwargs_marker = object()

current_request = contextvars.ContextVar("Current request")

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from qfieldcloud.core.models import Project


def set_current_request(request: HttpRequest | None) -> contextvars.Token:
    """Binds the request to the current thread.

    Args:
        request: Django request object, or `None` to reset

    Returns:
        The token that can be used to reset the context variable.
    """
    logger.debug("Save request in current thread")

    return current_request.set(request)


def get_current_request() -> HttpRequest | None:
    """Gets the request from the current thread.

    Returns:
        Django request object or `None` if no request is set.
    """
    return current_request.get(None)


def get_request_cache() -> BaseCache | None:
    """Return the current requests cache.

    Returns:
        The cache object associated with the current request, or `None` if no cache is available.
    """
    return getattr(get_current_request(), "cache", None)


def cache_calculate_key(args: tuple, kwargs: dict[str, Any]) -> str:
    """Calculate the cache key of a function call with args and kwargs.

    Returns:
        str: The calculated key for the function call.
    """
    # combine `args` with `kwargs`, separated by the `cache_args_kwargs_marker`
    key = tuple(args) + (cache_args_kwargs_marker,) + tuple(sorted(kwargs.items()))

    # return as a string
    return str(key)


def cache_for_request(
    key_modifier: Callable[..., tuple[tuple, dict[str, Any]]] | None = None,
) -> Callable:
    """Decorator that allows to cache a function call with parameters and its result only for the current request.

    The result is stored in the memory of the current process
    As soon as the request is destroyed, the cache is destroyed.

    Args:
        key_modifier: Optional callable to modify the input for the cache key, where the return values should be a tuple containing the modified `args` and `kwargs`.
    """

    def decorator(fn: Callable):
        def wrapper(*args, **kwargs):
            cache = get_request_cache()

            if not cache:
                # no cache found -> directly execute function without caching
                return fn(*args, **kwargs)

            if isinstance(key_modifier, Callable):
                modified_args, modified_kwargs = key_modifier(*args, **kwargs)
            else:
                modified_args, modified_kwargs = args, kwargs

            key = cache_calculate_key(modified_args, modified_kwargs)

            # cache found -> check if a result is already available for this function call
            try:
                result = getattr(cache, key)
            except AttributeError:
                # no result available -> execute function
                result = fn(*args, **kwargs)
                setattr(cache, key, result)

            return result

        return wrapper

    return decorator


def cache_project_for_request(request: HttpRequest, project: "Project") -> None:
    """Cache the given project for the current request."""
    cache = get_request_cache()

    if not cache:
        return

    if request.user.is_anonymous:
        return

    assert hasattr(request.user, "username")

    key = cache_calculate_key(
        args=(request.user.username, project.pk),
        kwargs={},
    )
    setattr(cache, key, project)


class RequestCache(LocMemCache):
    """`RequestCache` is a customized `LocMemCache` which stores its data cache as an instance attribute, rather than a global.

    It's designed to live only as long as the request object that `CurrentRequestMiddleware` attaches it to.
    """

    def __init__(self) -> None:
        # We explicitly do not call `super()` here, because while we want `BaseCache.__init__()` to run, we *don't*
        # want `LocMemCache.__init__()` to run, because that would store our caches in its globals.
        BaseCache.__init__(self, params={})

        self._cache = OrderedDict()
        self._expire_info = {}
        self._lock = Lock()


class CurrentRequestMiddleware:
    """Saves the current request in the context variable.

    This middleware saves the currently processed request
    in the working thread. This allows us to access the
    request everywhere, and don't need to pass it to every
    function.
    """

    def __init__(self, get_response: Callable) -> None:
        self.get_response = get_response

    def __call__(self, request) -> Any:
        set_current_request(request)

        request.cache = RequestCache()

        try:
            response = self.get_response(request)
        finally:
            set_current_request(None)

        return response
