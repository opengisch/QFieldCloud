import logging
from typing import Optional

from django.db.models import Q
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import ApplyJob, Delta, Job, PackageJob, Project, User

logger = logging.getLogger(__name__)


def apply_deltas(
    project, user, project_file, overwrite_conflicts, delta_ids=None
) -> Optional[ApplyJob]:
    """Apply a deltas"""

    logger.info(
        f"Requested apply_deltas on {project} with {project_file}; overwrite_conflicts: {overwrite_conflicts}; delta_ids: {delta_ids}"
    )

    apply_jobs = ApplyJob.objects.filter(
        project=project,
        status=[
            Job.Status.PENDING,
            Job.Status.QUEUED,
        ],
    )

    if len(apply_jobs) > 0:
        return apply_jobs[0]

    pending_deltas = Delta.objects.filter(
        project=project,
        last_status=Delta.Status.PENDING,
    )

    if delta_ids is not None:
        pending_deltas = pending_deltas.filter(pk__in=delta_ids)

    if len(pending_deltas) == 0:
        return None

    apply_job = ApplyJob.objects.create(
        project=project,
        created_by=user,
        overwrite_conflicts=overwrite_conflicts,
    )

    return apply_job


def repackage(project: Project, user: User) -> PackageJob:
    """Returns an unfinished or freshly created package job.

    Checks if there is already an unfinished package job and returns it,
    or creates a new package job and returns it.
    """
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    # Check if active package job already exists
    query = Q(project=project) & (
        Q(status=PackageJob.Status.PENDING)
        | Q(status=PackageJob.Status.QUEUED)
        | Q(status=PackageJob.Status.STARTED)
    )

    if PackageJob.objects.filter(query).count():
        return PackageJob.objects.get(query)

    package_job = PackageJob.objects.create(project=project, created_by=user)

    return package_job


def repackage_if_needed(project: Project, user: User) -> PackageJob:
    if not project.project_filename:
        raise exceptions.NoQGISProjectError()

    if project.needs_repackaging:
        package_job = repackage(project, user)
    else:
        package_job = (
            PackageJob.objects.filter(project=project).order_by("started_at").get()
        )

    return package_job
