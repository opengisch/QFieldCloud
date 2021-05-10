import warnings
from functools import reduce
from operator import and_, or_

from django.db.models import Q
from django.db.models.manager import BaseManager
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
    invert: bool = False,
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

    # one day conditions can be more than just pk check, please keep it for now
    conditions = []
    # exclude the already existing collaborators and the project owner
    if project:
        collaborator_ids = ProjectCollaborator.objects.filter(
            project=project
        ).values_list("collaborator", flat=True)
        user_ids = [*collaborator_ids, project.owner.pk]
        conditions = [Q(pk__in=user_ids)]

    # exclude the already existing members, the organization owner and the organization itself from the returned users
    elif organization:
        member_ids = OrganizationMember.objects.filter(
            organization=organization
        ).values_list("member", flat=True)
        user_ids = [
            *member_ids,
            organization.organization_owner.pk,
            organization.user_ptr.pk,
        ]
        conditions = [Q(pk__in=user_ids)]

    if conditions:
        if invert:
            users = users.filter(reduce(and_, [c for c in conditions]))
        else:
            users = users.exclude(reduce(or_, [c for c in conditions]))

    return users.order_by("-username")
