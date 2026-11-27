from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Any, NotRequired, TypedDict, TypeVar, cast

from constance import config
from django.core.cache import cache
from django.http import HttpRequest, QueryDict
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise


class DashboardPeriod(TypedDict):
    # The name shown in the period picker, e.g. "Last 30 days".
    title: StrOrPromise
    # How far back from now the period goes.
    duration: timedelta


class DashboardCardBreakdownRow(TypedDict):
    # The name of the row.
    label: StrOrPromise
    # The number shown at the end of the row.
    count: int
    # How much of the total this row is, from 0 to 100. Also sets how wide its bar is.
    percent: int


class DashboardCard(TypedDict):
    """A card of the admin dashboard, the `Args` of its `template` describe what each key shows."""

    # The template rendering the card, e.g. `admin/dashboards/stat.html`.
    template: str
    # The title at the top of the card.
    title: StrOrPromise
    # The text shown when hovering the info icon.
    hint: StrOrPromise
    # The big number, a count or an already formatted value such as a file size.
    value: int | str
    # When the numbers were calculated, shown as "Updated 5 minutes ago".
    computed_at: datetime
    # The number at the start of the line below the big number, e.g. "1,543".
    subvalue_count: NotRequired[int]
    # The text after it, e.g. "worked on projects (29%)".
    subvalue_text: NotRequired[str]
    # The list at the bottom of the card that splits the total into parts, e.g. the active users per client.
    # Each row shows a label, a number and a bar showing how much of the total it is.
    breakdown: NotRequired[list[DashboardCardBreakdownRow]]


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


def get_period_context(period: str) -> dict[str, Any]:
    """Returns the template context of the period picker."""
    return {
        "dashboard_period": period,
        "dashboard_period_title": DASHBOARD_PERIODS[period]["title"],
        "dashboard_periods": DASHBOARD_PERIODS,
    }


def get_dashboard_card_context(
    request: HttpRequest, get_card: Callable[[str], DashboardCard]
) -> dict[str, Any]:
    """Returns the template context of a single card and its period picker, for an admin page other than the dashboard.

    Args:
        request: the request, its `period` parameter picks the period
        get_card: returns the card of a period key.
    """
    period = get_period(request.GET)
    context = get_period_context(period)
    context["dashboard_card"] = get_card(period)

    return context


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
