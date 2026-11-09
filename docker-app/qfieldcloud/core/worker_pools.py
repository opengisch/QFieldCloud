from collections.abc import Iterable
from typing import NamedTuple

from django.db.models import Q, QuerySet

from qfieldcloud.core.models import Organization, Secret, WorkerPool
from qfieldcloud.project.models import Project


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
