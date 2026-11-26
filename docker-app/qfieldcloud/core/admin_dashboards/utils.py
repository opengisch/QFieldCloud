from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, TypedDict, TypeVar, cast
from zoneinfo import ZoneInfo

from constance import config
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, QuerySet
from django.db.models.functions import Trunc
from django.http import QueryDict
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.functional import Promise
from django.utils.translation import gettext
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

# What one bar of a bar chart covers, also the `kind` of Django's `Trunc`.
BarKind = Literal["hour", "day", "week"]

BAR_LENGTHS: dict[BarKind, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
}

# A period up to this long gets a bar per hour, a longer one up to `DAILY_BARS_MAX_DURATION` a bar per calendar day, and a longer one a bar per week.
HOURLY_BARS_MAX_DURATION = timedelta(days=1)
DAILY_BARS_MAX_DURATION = timedelta(days=90)

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


def get_bar_kind(duration: timedelta) -> BarKind:
    """Returns what one bar covers in the bar charts of a period of this `duration`, see `HOURLY_BARS_MAX_DURATION`."""
    if duration <= HOURLY_BARS_MAX_DURATION:
        return "hour"

    if duration <= DAILY_BARS_MAX_DURATION:
        return "day"

    return "week"


def get_bar_timezone(bar_kind: BarKind) -> tzinfo:
    """Returns the time zone the bars are counted in.

    Hours use UTC, which has no daylight saving time.
    Days and weeks use the server's `TIME_ZONE`, so all admins share the same cached days, whatever their own time zone.
    """
    if bar_kind == "hour":
        return UTC

    return ZoneInfo(settings.TIME_ZONE)


def get_current_bar_position(bar_kind: BarKind) -> datetime:
    """Returns the start of the current bar for the current hour, calendar day, or week starting on Monday."""
    now = timezone.now().astimezone(get_bar_timezone(bar_kind))

    if bar_kind == "hour":
        return now.replace(minute=0, second=0, microsecond=0)

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if bar_kind == "week":
        return today - timedelta(days=today.weekday())

    return today


def get_bar_positions(duration: timedelta) -> list[datetime]:
    """Returns the start of each bar of a period, oldest first."""
    bar_kind = get_bar_kind(duration)
    current_bar = get_current_bar_position(bar_kind)
    bar_length = BAR_LENGTHS[bar_kind]

    bars = []
    for bars_ago in range(round(duration / bar_length) - 1, -1, -1):
        bars.append(current_bar - bars_ago * bar_length)

    return bars


def get_bar_heights(
    queryset: QuerySet[Any], bars: list[datetime], bar_kind: BarKind
) -> list[int]:
    """Returns how many `queryset` rows were created in each bar, one number per bar in the order of `bars`, 0 for an empty bar."""
    rows = (
        queryset.filter(created_at__gte=bars[0])
        .annotate(bar=Trunc("created_at", bar_kind, tzinfo=get_bar_timezone(bar_kind)))
        .order_by()
        .values("bar")
        .annotate(count=Count("pk"))
    )

    count_by_bar: dict[datetime, int] = {}
    for row in rows:
        count_by_bar[row["bar"]] = row["count"]

    counts = []
    for bar in bars:
        counts.append(count_by_bar.get(bar, 0))

    return counts


def get_bar_labels(bars: list[datetime], bar_kind: BarKind) -> list[str]:
    """Returns the x-axis labels of the `bars`, a week is labelled with its first and last day, e.g. "Nov 16 – Nov 22".

    The current bar is labelled "This hour", "Today" or "This week", as it is not over yet.
    """
    current_bar = get_current_bar_position(bar_kind)
    current_label = gettext("Today")
    label_format = "M j"
    label_timezone = get_bar_timezone(bar_kind)
    if bar_kind == "hour":
        current_label = gettext("This hour")
        label_format = "H:i"
        label_timezone = timezone.get_current_timezone()
    elif bar_kind == "week":
        current_label = gettext("This week")

    labels = []
    for bar in bars:
        if bar == current_bar:
            labels.append(current_label)
            continue

        label = date_format(timezone.localtime(bar, label_timezone), label_format)

        if bar_kind == "week":
            last_day = timezone.localtime(bar, label_timezone) + timedelta(days=6)
            label = f"{label} – {date_format(last_day, label_format)}"

        labels.append(label)

    return labels


def get_bar_chart_options(multiple_series: bool) -> dict[str, Any]:
    """Returns the Chart.js options of a bar chart. A chart with multiple series stacks them."""
    return {
        "animation": False,
        "maintainAspectRatio": False,
        "datasets": {
            "bar": {
                "barPercentage": 0.8,
                "categoryPercentage": 1,
                "borderRadius": 2,
                "maxBarThickness": 32,
            },
        },
        "plugins": {
            "legend": {
                "display": multiple_series,
                "align": "end",
                "labels": {
                    "boxHeight": 6,
                    "boxWidth": 6,
                    "pointStyle": "circle",
                    "usePointStyle": True,
                },
            },
        },
        "scales": {
            "x": {
                "stacked": multiple_series,
                "border": {"display": False},
                "grid": {"display": False},
                "ticks": {"maxTicksLimit": 8},
            },
            "y": {
                "stacked": multiple_series,
                "beginAtZero": True,
                "border": {"display": False},
                "grid": {},
                "ticks": {"maxTicksLimit": 4, "precision": 0},
            },
        },
    }
