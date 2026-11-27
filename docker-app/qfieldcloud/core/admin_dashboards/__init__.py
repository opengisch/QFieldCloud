from typing import Any

from django.core.cache import cache
from django.http import HttpRequest

from qfieldcloud.core.admin_dashboards import active_users
from qfieldcloud.core.admin_dashboards.utils import (
    DASHBOARD_PERIODS,
    get_period,
    get_period_context,
)

# The cache key of every cached card, cleared together by the dashboard refresh button.
# A `{period}` in a key is filled in with every period label, a key without it is the same for all periods.
CARD_CACHE_KEYS = (active_users.ACTIVE_USERS_STATS_CACHE_KEY,)


def admin_dashboard_callback(
    request: HttpRequest, context: dict[str, Any]
) -> dict[str, Any]:
    """Adds the dashboard sections to the admin index context. Unfold calls this callback through `UNFOLD["DASHBOARD_CALLBACK"]`.

    A section lists its `cards` in display order. A card is a dict whose `template` key names the template that renders it.
    To add a card, call its function in a section below. If the card is cached, also add its cache key to `CARD_CACHE_KEYS`.
    """
    period = get_period(request.GET)

    context.update(get_period_context(period))
    context.update(
        {
            "dashboard_sections": [
                {
                    "cards": [
                        active_users.get_active_users_card(period),
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
