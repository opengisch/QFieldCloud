import warnings

from django.db.models import Q
from django.db.models.manager import BaseManager
from django.db.models.query import QuerySet
from qfieldcloud.core.models import (
    Delta,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    Team,
    TeamMember,
    User,
)


def get_available_projects(
    user,
    owner,
    ownerships=False,
    collaborations=False,
    memberships=False,
    public=False,
):
    """Return a queryset with all projects that are available to the `user`.
    The param `user` is meant to be the user that did the request and the `owner`
    is the user that has access to them.
    - owned `owner` or organization he belongs to and collaborated with `user`
    """

    warnings.warn(
        "`get_available_projects()` is deprecated. Use `owner.projects.for_user(user)` instead.",
        DeprecationWarning,
    )

    if not ownerships or not collaborations or not memberships or not public:
        raise Exception(
            "`get_available_projects()` was reimplemented and doesn't support excluding permissions from ownerships/collaborations/memberships anymore. Use `owner.projects.for_user(user)` instead and do the required filtering yourself."
        )

    return owner.projects.for_user(user, include_public=public)


def get_user_organizations(user: User, administered_only: bool = False) -> QuerySet:
    owned_organizations = Organization.objects.filter(
        organization_owner=user
    ).distinct()
    memberships = OrganizationMember.objects.filter(member=user)

    if administered_only:
        memberships = memberships.filter(role=OrganizationMember.Roles.ADMIN)

    membership_organizations = Organization.objects.filter(members__in=memberships)
    organizations = owned_organizations.union(membership_organizations)

    return organizations


def get_organization_teams(organization):
    return Team.objects.filter(team_organization=organization)


def get_team_members(team):
    return TeamMember.objects.filter(team=team)


def get_organization_members(organization):
    return OrganizationMember.objects.filter(organization=organization)


def get_project_deltas(project):
    """Return a queryset of all available deltas of a specific project."""
    return Delta.objects.filter(project=project)


def get_collaborators_of_project(project):
    """Return a queryset of all available collaborators of a specific project."""
    return ProjectCollaborator.objects.filter(project=project)


def get_users(
    username: str,
    project: Project = None,
    organization: Organization = None,
    exclude_organizations: bool = False,
    exclude_teams: bool = False,
) -> BaseManager:
    assert (
        project is None or organization is None
    ), "Cannot have the project and organization filters set simultaneously"

    if username:
        users = User.objects.filter(
            Q(username__icontains=username) | Q(email__icontains=username)
        )
    else:
        users = User.objects.all()

    if exclude_organizations:
        users = users.exclude(user_type=User.TYPE_ORGANIZATION)

    if exclude_teams:
        users = users.exclude(user_type=User.TYPE_TEAM)

    # exclude the already existing collaborators and the project owner
    if project:
        collaborator_ids = ProjectCollaborator.objects.filter(
            project=project
        ).values_list("collaborator", flat=True)
        users = users.exclude(pk__in=collaborator_ids)
        users = users.exclude(pk=project.owner.pk)

    # exclude the already existing members, the organization owner and the organization itself from the returned users
    if organization:
        member_ids = OrganizationMember.objects.filter(
            organization=organization
        ).values_list("member", flat=True)
        users = users.exclude(pk__in=member_ids)
        users = users.exclude(pk=organization.organization_owner.pk)
        users = users.exclude(pk=organization.user_ptr.pk)

    return users.order_by("-username")
