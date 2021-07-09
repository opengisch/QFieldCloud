import django_rq
from qfieldcloud.core.models import Job


def start_job(job: Job):  # noqa: F821
    """Call the orchestrator API and returns the RQ job"""
    job_id = str(job.id)

    if job.type == Job.Type.EXPORT:
        queue_name = "export"
        method = "export_project"
    elif job.type == Job.Type.DELTA_APPLY:
        queue_name = "deltas"
        method = "apply_deltas"
    elif job.type == Job.Type.PROCESS_PROJECTFILE:
        queue_name = "export"
        method = "process_projectfile"
    else:
        raise NotImplementedError(f"Unknown job type {job.type}")

    queue = django_rq.get_queue(queue_name)
    rq_job = queue.enqueue(
        f"orchestrator.orchestrator.{method}",
        job_id,
        job_id=job_id,
    )

    return rq_job
