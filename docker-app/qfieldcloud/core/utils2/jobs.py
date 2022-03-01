import logging
from typing import List, Optional

import qfieldcloud.core.models as models
from django.db.models import Q
from qfieldcloud.core import exceptions

logger = logging.getLogger(__name__)


def apply_deltas(
    project: "models.Project",
    user: "models.User",
    project_file: str,
    overwrite_conflicts: bool,
    delta_ids: List[str] = None,
) -> Optional["models.ApplyJob"]:
    """Apply a deltas"""

    logger.info(
        f"Requested apply_deltas on {project} with {project_file}; overwrite_conflicts: {overwrite_conflicts}; delta_ids: {delta_ids}"
    )

    apply_jobs = models.ApplyJob.objects.filter(
        project=project,
        status=[
            models.Job.Status.PENDING,
            models.Job.Status.QUEUED,
        ],
    )

    if len(apply_jobs) > 0:
        return apply_jobs[0]

    pending_deltas = models.Delta.objects.filter(
        project=project,
        last_status=models.Delta.Status.PENDING,
    )

    if delta_ids is not None:
        pending_deltas = pending_deltas.filter(pk__in=delta_ids)

    if len(pending_deltas) == 0:
        return None

    apply_job = models.ApplyJob.objects.create(
        project=project,
        created_by=user,
        overwrite_conflicts=overwrite_conflicts,
    )

    return apply_job


def repackage(project: "models.Project", user: "models.User") -> "models.PackageJob":
    """Returns an unfinished or freshly created package job.

    Checks if there is already an unfinished package job and returns it,
    or creates a new package job and returns it.
    """
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    # Check if active package job already exists
    query = Q(project=project) & (
        Q(status=models.PackageJob.Status.PENDING)
        | Q(status=models.PackageJob.Status.QUEUED)
        | Q(status=models.PackageJob.Status.STARTED)
    )

    if models.PackageJob.objects.filter(query).count():
        return models.PackageJob.objects.get(query)

    package_job = models.PackageJob.objects.create(project=project, created_by=user)

    return package_job


def repackage_if_needed(
    project: "models.Project", user: "models.User"
) -> "models.PackageJob":
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    if project.needs_repackaging:
        package_job = repackage(project, user)
    else:
        package_job = (
            models.PackageJob.objects.filter(project=project)
            .order_by("started_at")
            .get()
        )

    return package_job
