import logging

import django_rq
from qfieldcloud.core.models import Delta, DeltaApplyJob

logger = logging.getLogger(__name__)


def apply_deltas(
    project, user, project_file, overwrite_conflicts, delta_ids=None
) -> bool:
    """Call the orchestrator API to apply a delta file"""

    logger.info(
        f"Requested apply_deltas on {project} with {project_file}; overwrite_conflicts: {overwrite_conflicts}; delta_ids: {delta_ids}"
    )

    delta_apply_job = DeltaApplyJob.objects.create(
        project=project, created_by=user, overwrite_conflicts=overwrite_conflicts
    )
    pending_deltas = Delta.objects.filter(last_status__in=[Delta.Status.PENDING])

    if delta_ids is not None:
        pending_deltas = pending_deltas.filter(pk__in=delta_ids)

    if len(pending_deltas) == 0:
        return False

    for delta in pending_deltas:
        delta_apply_job.deltas_to_apply.add(delta)

    job_id = delta_apply_job.id
    queue = django_rq.get_queue("delta")
    queue.enqueue(
        "orchestrator.apply_deltas", str(job_id), str(project_file), job_id=str(job_id)
    )

    return True
