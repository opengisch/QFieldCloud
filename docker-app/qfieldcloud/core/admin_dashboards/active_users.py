from datetime import datetime, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any, TypedDict

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.admin_dashboards.utils import (
    DASHBOARD_PERIODS,
    get_or_compute_cached,
)
from qfieldcloud.core.models import Person, User

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise
else:
    StrOrPromise = str | Promise

ACTIVE_USERS_STATS_CACHE_KEY = "admin:dashboard:active_users:{period}:v1"


class ActiveUsersStats(TypedDict):
    # Number of distinct active users
    total_active_users: int
    # Number of distinct active users that logged in on the web.
    web_login_count: int
    # Number of distinct active users per token client type. A user may be counted in several client types.
    client_type_counts: dict[str, int]
    # Number of the distinct active users that also pushed a delta or triggered a job.
    project_active_count: int
    computed_at: datetime


def get_counted_client_types() -> list[AuthToken.ClientType]:
    """Returns the token client types that count as user activity."""
    client_types = []

    for client_type in AuthToken.ClientType:
        # Worker tokens are excluded from the counted client types.
        if client_type == AuthToken.ClientType.WORKER:
            continue

        client_types.append(client_type)

    return client_types


def compute_active_users_stats(period_duration: timedelta) -> ActiveUsersStats:
    """Computes the active users stats for a given time period."""
    now = timezone.now()
    period_start = now - period_duration

    active_tokens_qs = AuthToken.objects.filter(
        last_used_at__gte=period_start,
        user__type=User.Type.PERSON,
        user__is_active=True,
    ).exclude(
        client_type=AuthToken.ClientType.WORKER,
    )

    persons_qs = Person.objects.filter(
        is_active=True,
    )

    signed_in_persons_qs = persons_qs.filter(
        Q(last_login__gte=period_start) | Q(pk__in=active_tokens_qs.values("user_id"))
    )
    total_active_users = signed_in_persons_qs.count()

    project_active_count = signed_in_persons_qs.active(period_start, now).count()

    # web logins only set `User.last_login` and never touch an `AuthToken`, so they are counted separately from the client types
    web_login_count = persons_qs.filter(last_login__gte=period_start).count()

    client_type_counts: dict[str, int] = {}
    for client_type in get_counted_client_types():
        client_type_counts[client_type.value] = 0

    client_type_rows = (
        active_tokens_qs.order_by()
        .values("client_type")
        .annotate(users_count=Count("user_id", distinct=True))
    )
    for row in client_type_rows:
        client_type_counts[row["client_type"]] = row["users_count"]

    return {
        "total_active_users": total_active_users,
        "web_login_count": web_login_count,
        "client_type_counts": client_type_counts,
        "project_active_count": project_active_count,
        "computed_at": now,
    }


def get_active_users_stats(period: str) -> ActiveUsersStats:
    """Returns the active users stats for a given time period, when available from the cache."""
    return get_or_compute_cached(
        ACTIVE_USERS_STATS_CACHE_KEY.format(period=period),
        compute_active_users_stats,
        DASHBOARD_PERIODS[period]["duration"],
    )


def get_active_users_card(period: str) -> dict[str, Any]:
    """Returns the dashboard card with the number of active users in the `period`, e.g. `30d`."""
    stats = get_active_users_stats(period)

    return {
        "template": "admin/dashboards/stat.html",
        "title": _("Active users"),
        "hint": _("Users who logged in on the web or used a QFieldCloud client."),
        "value": stats["total_active_users"],
        "computed_at": stats["computed_at"],
    }


def get_active_users_by_client_card(period: str) -> dict[str, Any]:
    """Returns the card with the active users in the `period`, split by web login and client type, shown above the auth tokens list."""
    stats = get_active_users_stats(period)
    percent_base = max(stats["total_active_users"], 1)

    counts_by_label: list[tuple[StrOrPromise, int]] = [
        (_("Web login"), stats["web_login_count"]),
    ]
    for client_type in get_counted_client_types():
        count = stats["client_type_counts"].get(client_type.value, 0)
        counts_by_label.append((client_type.label, count))

    breakdown: list[dict[str, Any]] = []
    for label, count in counts_by_label:
        if count == 0:
            continue

        breakdown.append(
            {
                "label": label,
                "count": count,
                "percent": round(count * 100 / percent_base),
            }
        )

    breakdown.sort(key=itemgetter("count"), reverse=True)

    project_active_percent = round(stats["project_active_count"] * 100 / percent_base)

    return {
        "template": "admin/dashboards/stat.html",
        "title": _("Active users"),
        "hint": _(
            "Users who logged in on the web or used a QFieldCloud client. "
            "The total counts each user once, and a user using several clients shows up in multiple rows below. "
            "Worked on projects counts the users who also have pushed a delta or triggered a job."
        ),
        "value": stats["total_active_users"],
        "subvalue_count": stats["project_active_count"],
        "subvalue_text": _("worked on projects ({percent}%)").format(
            percent=project_active_percent
        ),
        "breakdown": breakdown,
        "computed_at": stats["computed_at"],
    }
