from collections.abc import Iterable
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import Job, Organization, Secret, WorkerPool
from qfieldcloud.project.models import Project

# Extra time after the job timeout, so a job that used all of it can still report its result.
TOKEN_EXPIRATION_TIME_BUFFER = timedelta(seconds=60)


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


def claim_job(pool: WorkerPool) -> ClaimedJob | None:
    """Starts the oldest job `pool` may run and returns it, with the token for its runner."""
    if pool.organization:
        jobs = Job.objects.claimable().filter(project__owner=pool.organization)
    else:
        jobs = get_jobs_outside_own_pools()

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
            expires_at=timezone.now()
            + timedelta(seconds=settings.QFIELDCLOUD_WORKER_TIMEOUT_S)
            + TOKEN_EXPIRATION_TIME_BUFFER,
        )

    return ClaimedJob(job=job, token=token.key)
