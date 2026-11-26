import json
from datetime import datetime, timedelta
from typing import Any, TypedDict

from django.utils import timezone
from django.utils.translation import gettext as _

from qfieldcloud.core.admin_dashboards.utils import (
    DASHBOARD_PERIODS,
    BarKind,
    get_bar_chart_options,
    get_bar_heights,
    get_bar_kind,
    get_bar_labels,
    get_bar_positions,
    get_or_compute_cached,
)
from qfieldcloud.project.models import Project

NEW_PROJECTS_CACHE_KEY = "admin:dashboard:new_projects:{period}:v1"


class NewProjectsStats(TypedDict):
    # When each bar starts, see `get_period_bars`.
    bars: list[datetime]
    # What each bar covers, an hour, a calendar day or a week.
    bar_kind: BarKind
    # Number of projects created in each of the `bars`. Deleted projects are not counted.
    counts: list[int]
    total: int
    computed_at: datetime


def compute_new_projects_stats(period_duration: timedelta) -> NewProjectsStats:
    """Counts the new projects in each bar of the given time period."""
    bars = get_bar_positions(period_duration)
    bar_kind = get_bar_kind(period_duration)
    counts = get_bar_heights(Project.objects.all(), bars, bar_kind)

    return {
        "bars": bars,
        "bar_kind": bar_kind,
        "counts": counts,
        "total": sum(counts),
        "computed_at": timezone.now(),
    }


def get_new_projects_card(period: str) -> dict[str, Any]:
    """Returns the dashboard card with a bar chart of the projects created in the given period."""
    stats = get_or_compute_cached(
        NEW_PROJECTS_CACHE_KEY.format(period=period),
        compute_new_projects_stats,
        DASHBOARD_PERIODS[period]["duration"],
    )
    chart_data = {
        "labels": get_bar_labels(stats["bars"], stats["bar_kind"]),
        "datasets": [
            {
                "label": _("New projects"),
                "data": stats["counts"],
                "backgroundColor": "var(--color-primary-600)",
            },
        ],
    }

    return {
        "template": "admin/dashboards/bar_chart.html",
        "title": _("New projects"),
        "hint": _(
            "Projects created in a given period of time. Deleted projects are not counted."
        ),
        "value": stats["total"],
        "computed_at": stats["computed_at"],
        "chart_data": json.dumps(chart_data),
        "chart_options": json.dumps(get_bar_chart_options(multiple_series=False)),
    }
