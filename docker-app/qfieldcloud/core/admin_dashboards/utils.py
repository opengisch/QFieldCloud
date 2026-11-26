from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar, cast

from constance import config
from django.core.cache import cache
from django.http import QueryDict
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise
else:
    StrOrPromise = str | Promise


class DashboardPeriod(TypedDict):
    title: StrOrPromise
    duration: timedelta


# The periods an admin can pick for the dashboard, each counted back from now.
# The key is used in the `period` parameter and in the cache keys of the cards.
DASHBOARD_PERIODS: dict[str, DashboardPeriod] = {
    "24h": {"title": _("Last 24 hours"), "duration": timedelta(hours=24)},
    "7d": {"title": _("Last 7 days"), "duration": timedelta(days=7)},
    "30d": {"title": _("Last 30 days"), "duration": timedelta(days=30)},
    "90d": {"title": _("Last 90 days"), "duration": timedelta(days=90)},
    "1y": {"title": _("Last year"), "duration": timedelta(days=365)},
}
DEFAULT_DASHBOARD_PERIOD = "30d"

T = TypeVar("T")


def get_period(query_dict: QueryDict) -> str:
    """Returns the period of the `period` parameter, such as `30d`, or the default period when it is missing or unknown."""
    period = query_dict.get("period", "")

    if period in DASHBOARD_PERIODS:
        return period

    return DEFAULT_DASHBOARD_PERIOD


def get_or_compute_cached(
    cache_key: str, compute: Callable[..., T], *compute_args: Any
) -> T:
    """Returns the value cached under `cache_key`, or computes it with `compute(*compute_args)` and caches it for `ADMIN_DASHBOARDS_CACHE_TTL_MINUTES` minutes.

    A TTL of 0 disables the cache. If the cache is unreachable, the value is computed on every call.
    """
    cache_ttl_s = config.ADMIN_DASHBOARDS_CACHE_TTL_MINUTES * 60

    # `get_or_set` returns whatever `compute` returns or what was cached from it
    return cast(
        "T", cache.get_or_set(cache_key, partial(compute, *compute_args), cache_ttl_s)
    )
