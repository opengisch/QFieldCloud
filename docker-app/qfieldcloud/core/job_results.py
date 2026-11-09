from datetime import datetime

from django.utils import timezone

from qfieldcloud.core.models import ApplyJob, ApplyJobDelta, Delta, Job
from qfieldcloud.core.utils2 import packages
from qfieldcloud.project.models import QgisProject


def apply_package_result(job: Job, data_last_packaged_at: datetime | None) -> None:
    """Records when the project was packaged and deletes obsolete packages. Only for successfully finished jobs."""
    # only successfully finished packaging jobs should update the Project.data_last_packaged_at
    job.project.data_last_packaged_at = data_last_packaged_at
    job.project.save(update_fields=("data_last_packaged_at",))

    packages.delete_obsolete_packages(projects=[job.project])


def apply_delta_results(job: ApplyJob) -> None:
    """Stores the outcome of each delta from the feedback of a successfully finished job.

    Only deltas of `job` are changed, whatever the feedback contains. The project counts as modified unless every delta was reported as a conflict or as failed.
    """
    delta_feedback = job.feedback["outputs"]["apply_deltas"]["delta_feedback"]
    is_data_modified = False

    for feedback in delta_feedback:
        delta_id = feedback["delta_id"]
        status = feedback["status"]
        modified_pk = feedback["modified_pk"]

        if status == "status_applied":
            status = Delta.Status.APPLIED
            is_data_modified = True
        elif status == "status_conflict":
            status = Delta.Status.CONFLICT
        elif status == "status_apply_failed":
            status = Delta.Status.NOT_APPLIED
        else:
            status = Delta.Status.ERROR
            # not certain what happened
            is_data_modified = True

        # NOTE only deltas of this job, as workers may run outside of our control
        job.deltas_to_apply.filter(pk=delta_id).update(
            last_status=status,
            last_feedback=feedback,
            last_modified_pk=modified_pk,
            last_apply_attempt_at=job.started_at,
            last_apply_attempt_by=job.created_by,
        )

        ApplyJobDelta.objects.filter(
            apply_job_id=job.pk,
            delta_id=delta_id,
        ).update(
            status=status,
            feedback=feedback,
            modified_pk=modified_pk,
        )

    if is_data_modified:
        job.project.data_last_updated_at = timezone.now()
        job.project.save(update_fields=("data_last_updated_at",))


def apply_project_details(job: Job) -> None:
    """Stores the project details from the feedback of a successful `process_projectfile` job.

    Expects the project to have its QGIS file.
    """
    project = job.project
    details = job.feedback["outputs"]["project_details"]["project_details"]

    # Since the `Project.qgis_version` field is newly added, we want to backfill it for old projects that didn't have it set,
    # but the `process_projectfile` job can detect the QGIS version from the project file and return it in the feedback, we can set it here.
    # NOTE `Project.qgis_version` is used by `wrapper.JobRun.get_qgis_image()` to detect
    # the correct QGIS docker image to run the job.
    # Therefore, we cannot use the very similar `QgisProject.qgis_version` field,
    # which is not populated until the first `process_projectfile` job is run.
    if project.qgis_version is None and details.get("qgis_version"):
        project.qgis_version = details["qgis_version"]
        project.save(update_fields=["qgis_version"])

    QgisProject.objects.update_from_details(
        project, project.the_qgis_file.latest_version, details
    )


def apply_job_result(job: Job) -> None:
    """Applies the result of a successful job that ran on a worker pool."""
    if job.type == Job.Type.PACKAGE:
        apply_package_result(job, job.started_at)
    elif job.type == Job.Type.DELTA_APPLY:
        apply_delta_results(ApplyJob.objects.get(pk=job.pk))
    elif job.type == Job.Type.PROCESS_PROJECTFILE:
        apply_project_details(job)
