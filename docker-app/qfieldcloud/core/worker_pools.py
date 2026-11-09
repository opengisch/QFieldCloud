import json
import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import IO, Any, NamedTuple

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.exceptions import (
    JobDeltafileAlreadyFetchedError,
    JobSecretsAlreadyFetchedError,
    JobSecretsMissingError,
    WorkerJobNotFoundError,
)
from qfieldcloud.core.job_results import apply_job_result, prepare_deltafile
from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    Job,
    Organization,
    SealedSecretValue,
    Secret,
    WorkerPool,
)
from qfieldcloud.project.models import Project, ProjectSeed

logger = logging.getLogger(__name__)

# The QGIS version of projects that do not have one yet.
DEFAULT_QGIS_MAJOR_VERSION = 3

# Above this a result can no longer be stored reliably in a database column.
MAX_JOB_RESULT_BYTES = 200 * 1000 * 1000

# Time the launcher has to fetch the secrets and data of a job, before the job timeout starts.
JOB_SETUP_TIMEOUT = timedelta(minutes=5)

# Time the runner has after the job timeout to report the result, the runner is told with each claim.
JOB_REPORT_TIMEOUT = timedelta(minutes=10)


def get_job_time_limit() -> timedelta:
    """Returns how long a job claimed by a pool may stay started, until its token expires and the job counts as terminated."""
    return (
        JOB_SETUP_TIMEOUT
        + timedelta(seconds=settings.QFIELDCLOUD_WORKER_TIMEOUT_S)
        + JOB_REPORT_TIMEOUT
    )


class ClaimedJob(NamedTuple):
    """A started job and the token its runner authenticates with."""

    job: Job
    token: str


class AffectedResources(NamedTuple):
    """The secrets and projects that a pool change would affect."""

    secrets: QuerySet[Secret]
    projects: QuerySet[Project]


def _get_affected_resources(secrets: QuerySet[Secret]) -> AffectedResources:
    project_secrets = secrets.filter(project__isnull=False).values("project_id")
    organization_secrets = secrets.filter(organization__isnull=False).values(
        "organization_id"
    )

    return AffectedResources(
        secrets=secrets.select_related("project", "organization").distinct(),
        projects=Project.objects.filter(
            Q(pk__in=project_secrets) | Q(owner_id__in=organization_secrets)
        ).order_by("name"),
    )


def get_resources_affected_by_pool_removal(
    pools: Iterable[WorkerPool],
) -> AffectedResources:
    """Returns what loses its secrets when `pools` are deleted or get their key reset."""
    return _get_affected_resources(Secret.objects.filter(sealed_values__pool__in=pools))


def get_resources_affected_by_new_pool(organization: Organization) -> AffectedResources:
    """Returns what loses its secrets when `organization` moves to its own pool."""
    return _get_affected_resources(
        Secret.objects.filter(
            Q(organization=organization) | Q(project__owner=organization),
            sealed_values__isnull=False,
        )
    )


def get_jobs_outside_own_pools() -> QuerySet[Job]:
    """Returns the claimable jobs of owners on the global pool."""
    own_pool_owners = WorkerPool.objects.filter(organization__isnull=False).values(
        "organization_id"
    )

    return Job.objects.claimable().exclude(project__owner_id__in=own_pool_owners)


def _filter_jobs_by_qgis_version(
    jobs: QuerySet[Job], qgis_major_version: int
) -> QuerySet[Job]:
    """Keeps the jobs that run on the given QGIS major version, projects without a version run on QGIS 3.

    A project being created takes the version of the project it is cloned from.
    """
    prefix = f"{qgis_major_version}."
    clones_this_version = Exists(
        ProjectSeed.objects.filter(
            project=OuterRef("project"),
            clone_from_project__qgis_version__startswith=prefix,
        )
    )
    clones_any_version = Exists(
        ProjectSeed.objects.filter(
            project=OuterRef("project"),
            clone_from_project__qgis_version__isnull=False,
        )
    )
    no_version = Q(project__qgis_version__isnull=True)
    is_create_project = Q(type=Job.Type.CREATE_PROJECT)

    matching = Q(project__qgis_version__startswith=prefix) | Q(
        no_version, is_create_project, clones_this_version
    )

    if qgis_major_version == DEFAULT_QGIS_MAJOR_VERSION:
        matching |= Q(no_version) & (Q(~is_create_project) | Q(~clones_any_version))

    return jobs.filter(matching)


def claim_job(
    pool: WorkerPool, qgis_major_version: int = DEFAULT_QGIS_MAJOR_VERSION
) -> ClaimedJob | None:
    """Starts the oldest job `pool` may run on its QGIS version and returns it, with the token for its runner."""
    if pool.organization:
        jobs = Job.objects.claimable().filter(project__owner=pool.organization)
    else:
        jobs = get_jobs_outside_own_pools()

    jobs = _filter_jobs_by_qgis_version(jobs, qgis_major_version)

    with transaction.atomic():
        # NOTE a job without its creator has no user for the token and would block the queue
        job = jobs.filter(created_by__isnull=False).first()

        if not job:
            return None

        job.status = Job.Status.STARTED
        job.started_at = timezone.now()
        job.worker_pool = pool
        job.save(update_fields=["status", "started_at", "worker_pool"])

        token = AuthToken.objects.create(
            user=job.created_by,
            client_type=AuthToken.ClientType.WORKER,
            job=job,
            expires_at=job.started_at + get_job_time_limit(),
        )

    return ClaimedJob(job=job, token=token.key)


def _mark_job_failed(job: Job) -> None:
    job.status = Job.Status.FAILED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at"])

    if job.type == Job.Type.PROCESS_PROJECTFILE and hasattr(
        job.project, "qgis_project"
    ):
        job.project.qgis_project.delete()

    if job.type == Job.Type.DELTA_APPLY:
        ApplyJob.objects.get(id=job.id).deltas_to_apply.update(
            last_status=Delta.Status.ERROR,
            last_feedback=None,
            last_modified_pk=None,
            last_apply_attempt_at=job.started_at,
            last_apply_attempt_by=job.created_by,
        )
        ApplyJobDelta.objects.filter(apply_job_id=job.id).update(
            status=Delta.Status.ERROR,
            feedback=None,
            modified_pk=None,
        )


def _get_error_feedback(error: str, error_type: str) -> dict[str, Any]:
    return {
        "error": error,
        "error_type": error_type,
        "error_class": "",
        "error_origin": "worker_pool",
        "error_stack": "",
    }


def fail_job(job: Job, error: str, error_type: str) -> None:
    """Marks a running job as failed with an error shown to the user."""
    job.output = error
    job.feedback = _get_error_feedback(error, error_type)
    job.save(update_fields=["output", "feedback"])

    _mark_job_failed(job)


def _read_job_output(output_file: IO[bytes] | None) -> str:
    if not output_file:
        return ""

    # NOTE postgres text cannot contain NUL characters, which project code could print
    return (
        output_file.read(MAX_JOB_RESULT_BYTES)
        .decode("utf-8", errors="replace")
        .replace("\x00", "")
    )


def _read_job_feedback(feedback_file: IO[bytes] | None) -> dict[str, Any]:
    if not feedback_file:
        return _get_error_feedback("The job sent no feedback.", "INVALID_RESULT")

    contents = feedback_file.read(MAX_JOB_RESULT_BYTES + 1)

    if len(contents) > MAX_JOB_RESULT_BYTES:
        return _get_error_feedback("The job feedback is too large.", "RESULT_TOO_LARGE")

    try:
        feedback = json.loads(contents)
    except ValueError:
        return _get_error_feedback("The job feedback is invalid.", "INVALID_RESULT")

    if not isinstance(feedback, dict):
        return _get_error_feedback("The job feedback is invalid.", "INVALID_RESULT")

    if feedback.get("error"):
        feedback["error_origin"] = "container"

    return feedback


def complete_job(
    job_id: str,
    token: AuthToken,
    exit_code: int,
    timed_out: bool,
    feedback_file: IO[bytes] | None,
    output_file: IO[bytes] | None,
) -> None:
    """Stores the result of a job that ran on a worker pool and ends the job and its token.

    A job that timed out fails with a timeout error, whatever feedback it wrote before it was stopped.
    """
    with transaction.atomic():
        job = (
            Job.objects.select_for_update()
            .filter(
                pk=job_id,
                created_by=token.user,
                worker_pool__isnull=False,
                status=Job.Status.STARTED,
            )
            # NOTE a token only completes the job it was created for, never another job of the same user
            .filter(pk=token.job_id)
            .first()
        )

        if not job:
            raise WorkerJobNotFoundError()

        job.output = _read_job_output(output_file)

        if timed_out:
            job.output += f"\nTimeout error! The job failed to finish within {settings.QFIELDCLOUD_WORKER_TIMEOUT_S} seconds!\n"
            job.feedback = _get_error_feedback("Worker timeout error.", "TIMEOUT")
        else:
            job.feedback = _read_job_feedback(feedback_file)

        job.feedback["container_exit_code"] = exit_code
        job.save(update_fields=["output", "feedback"])

        token.expires_at = timezone.now()
        token.save(update_fields=["expires_at"])

        if exit_code != 0 or job.feedback.get("error") is not None:
            _mark_job_failed(job)
            return

        try:
            with transaction.atomic():
                apply_job_result(job)
        except Exception as err:  # noqa: BLE001
            logger.error(f"Failed to apply the result of job {job.pk}", exc_info=err)
            job.feedback.update(
                _get_error_feedback("The job result is invalid.", "INVALID_RESULT")
            )
            job.save(update_fields=["feedback"])
            _mark_job_failed(job)
            return

        job.status = Job.Status.FINISHED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])


def _get_missing_secret_names(
    secrets: list[Secret], sealed_values: list[SealedSecretValue]
) -> list[str]:
    sealed_secrets = {sealed_value.secret.pk for sealed_value in sealed_values}

    return sorted(secret.name for secret in secrets if secret.pk not in sealed_secrets)


def fetch_job_secrets(job_id: str, pool: WorkerPool) -> list[SealedSecretValue]:
    """Returns the sealed secrets of a running job, once. A job with unreadable secrets fails instead of running without them."""
    missing_secret_names = []

    with transaction.atomic():
        job = (
            Job.objects.select_for_update()
            .filter(pk=job_id, worker_pool=pool, status=Job.Status.STARTED)
            .first()
        )

        if not job:
            raise WorkerJobNotFoundError()

        if job.secrets_fetched_at:
            raise JobSecretsAlreadyFetchedError()

        job.secrets_fetched_at = timezone.now()
        job.save(update_fields=["secrets_fetched_at"])

        secrets = []

        # NOTE a job whose user no longer exists cannot have its personal secrets resolved
        if job.triggered_by:
            secrets = list(
                Secret.objects.for_user_and_project(job.triggered_by, job.project)  # type: ignore[attr-defined]
            )

        sealed_values = list(
            SealedSecretValue.objects.select_related("secret").filter(
                secret__in=secrets, pool=pool, key_id=pool.key_id
            )
        )
        missing_secret_names = _get_missing_secret_names(secrets, sealed_values)

        if missing_secret_names:
            names = ", ".join(missing_secret_names)
            fail_job(
                job,
                f"The job cannot run because these secrets must be entered again: {names}",
                "MISSING_SECRETS",
            )

    # NOTE raised outside of the transaction, so the failed job is saved
    if missing_secret_names:
        raise JobSecretsMissingError(detail=missing_secret_names)

    return sealed_values


def fetch_job_deltafile(job_id: str, pool: WorkerPool) -> dict[str, Any]:
    """Returns the deltafile of a running delta job of `pool` and marks its deltas as started, once."""
    with transaction.atomic():
        job = (
            ApplyJob.objects.select_for_update()
            .filter(pk=job_id, worker_pool=pool, status=Job.Status.STARTED)
            .first()
        )

        if not job:
            raise WorkerJobNotFoundError()

        if job.deltafile_fetched_at:
            raise JobDeltafileAlreadyFetchedError()

        job.deltafile_fetched_at = timezone.now()
        job.save(update_fields=["deltafile_fetched_at"])

        return prepare_deltafile(job)
