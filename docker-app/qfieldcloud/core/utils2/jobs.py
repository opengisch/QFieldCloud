import logging
from typing import Optional

from qfieldcloud.core.models import ApplyJob, Delta, Job

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
