from typing import Any

from django.core.cache import cache
from django.http import HttpRequest

from qfieldcloud.core.admin_dashboards import (
    active_users,
    new_jobs,
    new_projects,
    storage_sizes,
)
from qfieldcloud.core.admin_dashboards.utils import DASHBOARD_PERIODS, get_period

# The cache key of every cached card, cleared together by the dashboard refresh button.
# A `{period}` in a key is filled in with every period label, a key without it is the same for all periods.
CARD_CACHE_KEYS = (
    active_users.ACTIVE_USERS_STATS_CACHE_KEY,
    new_projects.NEW_PROJECTS_CACHE_KEY,
    new_jobs.NEW_JOBS_CACHE_KEY,
    storage_sizes.STORAGE_STATS_CACHE_KEY,
)


def admin_dashboard_callback(
    request: HttpRequest, context: dict[str, Any]
) -> dict[str, Any]:
    """Adds the dashboard sections to the admin index context. Unfold calls this callback through `UNFOLD["DASHBOARD_CALLBACK"]`.

    A section lists its `cards` in display order, below its optional `title` on a separator line.
    A card is a dict whose `template` key names the template that renders it.
    Optional `columns` and `rows` are how many cells of the dashboard grid a chart card spans, 1 by default.
    To add a card, call its function in a section below. If the card is cached, also add its cache key to `CARD_CACHE_KEYS`.
    """
    period = get_period(request.GET)

    context.update(
        {
            "dashboard_period": period,
            # shown on the period picker button, e.g. "Last 30 days"
            "dashboard_period_title": DASHBOARD_PERIODS[period]["title"],
            "dashboard_periods": DASHBOARD_PERIODS,
            "dashboard_sections": [
                {
                    "title": None,
                    # New projects and new jobs charts span two rows, so the storage card fills the cell below the active users
                    "cards": [
                        active_users.get_active_users_card(period),
                        {**new_projects.get_new_projects_card(period), "rows": 2},
                        {**new_jobs.get_new_jobs_card(period), "rows": 2},
                        storage_sizes.get_storage_card(),
                    ],
                },
            ],
        }
    )

    return context


def clear_admin_dashboards_cache() -> None:
    """Removes the cached stats of every card and period, so the next dashboard view recomputes them."""
    # a set, as a key without `{period}` is the same for every period
    cache_keys = set()

    for cache_key in CARD_CACHE_KEYS:
        for period in DASHBOARD_PERIODS:
            cache_keys.add(cache_key.format(period=period))

    cache.delete_many(list(cache_keys))
