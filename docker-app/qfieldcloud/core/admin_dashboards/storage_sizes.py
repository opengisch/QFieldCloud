from datetime import datetime
from typing import Any, TypedDict

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from qfieldcloud.core.admin_dashboards.utils import get_or_compute_cached
from qfieldcloud.core.templatetags.filters import filesizeformat10
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.project.models import Project

STORAGE_STATS_CACHE_KEY = "admin:dashboard:storage:v1"


class StorageStats(TypedDict):
    # Size in bytes of every version of the project files, the sum of `Project.file_storage_bytes`.
    project_files_bytes: int
    # Size in bytes of every version of the package files.
    package_files_bytes: int
    computed_at: datetime


def compute_storage_stats() -> StorageStats:
    """Sums the size of the project and package files from the database."""
    project_files_bytes = Project.objects.aggregate(
        total=Sum("file_storage_bytes", default=0)
    )["total"]
    package_files_bytes = FileVersion.objects.filter(
        file__file_type=File.FileType.PACKAGE_FILE
    ).aggregate(total=Sum("size", default=0))["total"]

    return {
        "project_files_bytes": project_files_bytes,
        "package_files_bytes": package_files_bytes,
        "computed_at": timezone.now(),
    }


def get_storage_card() -> dict[str, Any]:
    """Returns the dashboard card with the size of all project and package files."""
    stats = get_or_compute_cached(STORAGE_STATS_CACHE_KEY, compute_storage_stats)

    return {
        "template": "admin/dashboards/stat.html",
        "title": _("Total project storage"),
        "hint": _("The size of project and package files. "),
        "value": filesizeformat10(stats["project_files_bytes"]),
        "computed_at": stats["computed_at"],
    }
