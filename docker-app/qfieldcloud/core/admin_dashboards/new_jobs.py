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
from qfieldcloud.core.models import Job

NEW_JOBS_CACHE_KEY = "admin:dashboard:new_jobs:{period}:v1"

# Pre assign color for each job type, the colors are defined in `qfc_admin.css`
JOB_TYPE_COLORS = (
    (Job.Type.PACKAGE, "var(--qfc-chart-series-1)"),
    (Job.Type.DELTA_APPLY, "var(--qfc-chart-series-2)"),
    (Job.Type.PROCESS_PROJECTFILE, "var(--qfc-chart-series-3)"),
    (Job.Type.CREATE_PROJECT, "var(--qfc-chart-series-4)"),
)


class NewJobsStats(TypedDict):
    # When each bar starts.
    bars: list[datetime]
    # What each bar covers, an hour, a calendar day or a week.
    bar_kind: BarKind
    # Number of jobs created in each of the `bars`, per job type.
    counts_by_type: dict[str, list[int]]
    total: int
    computed_at: datetime


def compute_new_jobs_stats(period_duration: timedelta) -> NewJobsStats:
    """Counts the jobs of each type in each bar of the given period."""
    bars = get_bar_positions(period_duration)
    bar_kind = get_bar_kind(period_duration)
    counts_by_type: dict[str, list[int]] = {}
    total = 0

    for job_type, _color in JOB_TYPE_COLORS:
        counts = get_bar_heights(Job.objects.filter(type=job_type), bars, bar_kind)
        counts_by_type[job_type.value] = counts
        total += sum(counts)

    return {
        "bars": bars,
        "bar_kind": bar_kind,
        "counts_by_type": counts_by_type,
        "total": total,
        "computed_at": timezone.now(),
    }


def get_new_jobs_card(period: str) -> dict[str, Any]:
    """Returns a dashboard card with a jobs chart for a given period."""
    stats = get_or_compute_cached(
        NEW_JOBS_CACHE_KEY.format(period=period),
        compute_new_jobs_stats,
        DASHBOARD_PERIODS[period]["duration"],
    )

    datasets = []
    for job_type, color in JOB_TYPE_COLORS:
        datasets.append(
            {
                "label": str(job_type.label),
                "data": stats["counts_by_type"][job_type.value],
                "backgroundColor": color,
            }
        )

    chart_data = {
        "labels": get_bar_labels(stats["bars"], stats["bar_kind"]),
        "datasets": datasets,
    }

    return {
        "template": "admin/dashboards/bar_chart.html",
        "title": _("Jobs"),
        "hint": _("Jobs created in a given period of time, per job type."),
        "value": stats["total"],
        "computed_at": stats["computed_at"],
        "chart_data": json.dumps(chart_data),
        "chart_options": json.dumps(get_bar_chart_options(multiple_series=True)),
    }
