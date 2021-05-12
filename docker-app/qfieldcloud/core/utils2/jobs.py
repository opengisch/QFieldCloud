import logging

import django_rq
from qfieldcloud.core.models import ApplyJob, ApplyJobDelta, Delta

logger = logging.getLogger(__name__)


def apply_deltas(
    project, user, project_file, overwrite_conflicts, delta_ids=None
) -> bool:
    """Call the orchestrator API to apply a delta file"""

    logger.info(
        f"Requested apply_deltas on {project} with {project_file}; overwrite_conflicts: {overwrite_conflicts}; delta_ids: {delta_ids}"
    )

    queue = django_rq.get_queue("delta")
    job_ids = queue.started_job_registry.get_job_ids()

    delta_apply_job = ApplyJob.objects.create(
        project=project, created_by=user, overwrite_conflicts=overwrite_conflicts
    )
    pending_deltas = Delta.objects.filter(
        last_status__in=[
            # do not include deltas with NOT_APPLIED status, as it is a final status
            Delta.Status.PENDING,
            Delta.Status.STARTED,
            Delta.Status.ERROR,
        ],
    ).exclude(
        id__in=ApplyJobDelta.objects.filter(delta_apply_job_id__in=job_ids).values("delta_id")
    )

    if delta_ids is not None:
        pending_deltas = pending_deltas.filter(pk__in=delta_ids)

    if len(pending_deltas) == 0:
        return False

    for delta in pending_deltas:
        delta_apply_job.deltas_to_apply.add(delta)

    job_id = delta_apply_job.id
    queue.enqueue(
        "orchestrator.apply_deltas", str(job_id), str(project_file), job_id=str(job_id)
    )

    return True
