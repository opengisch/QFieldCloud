from django.db.models import Q

from qfieldcloud.core.models import (
    Project, ProjectCollaborator, OrganizationMember,
    Organization, Delta, User)

from qfieldcloud.core.permissions_utils import can_list_deltas


def get_available_projects(user, include_public=False):
    """Return a queryset with all projects that are available to the `user`.
    The param `user` is meant to be the user that did the request"""

    queryset = (Project.objects.filter(
        owner=user) | Project.objects.filter(
            collaborators__in=ProjectCollaborator.objects.filter(
                collaborator=user))).distinct()

    if include_public:
        queryset |= Project.objects.filter(private=False).distinct()

    # Get all the organizations where the `user` is admin
    org_admin = OrganizationMember.objects.filter(
        member=user,
        role=OrganizationMember.ROLE_ADMIN).values('organization')

    # Add all the projects of the organizations where `user` is admin
    queryset |= Project.objects.filter(owner__in=org_admin).distinct()

    return queryset


def get_projects_of_owner(user, owner):
    """Return a queryset with all the projects of `owner` that
    are visible to `user`. The param `user` is meant to be the
    user that did the request"""

    # If the user is the owner return all projects
    if owner == user:
        return Project.objects.filter(owner=owner)

    # If the user is owner of the organitazion return all projects
    if type(owner) == Organization and owner.organization_owner == user:
        return Project.objects.filter(owner=owner)

    # If the user is an admin of the organization return all projects
    if OrganizationMember.objects.filter(
            organization=owner,
            member=user,
            role=OrganizationMember.ROLE_ADMIN).exists():
        return Project.objects.filter(owner=owner)

    # Get all the project where `user` is a collaborator
    queryset = (Project.objects.filter(
        owner=owner,
        collaborators__in=ProjectCollaborator.objects.filter(
            collaborator=user))).distinct()

    # Add all the public projects of `owner`
    queryset |= Project.objects.filter(owner=owner, private=False).distinct()

    return queryset


def get_all_public_projects():
    """Return all public projects."""
    return Project.objects.filter(private=False)


def get_deltas_of_project(project):
    """Return a queryset of all available deltas of a specific project."""
    return Delta.objects.filter(project=project)


def get_collaborators_of_project(project):
    """Return a queryset of all available collaborators of a specific project."""
    return ProjectCollaborator.objects.filter(project=project)


def get_possible_collaborators_of_project(user, project):
    """Return a queryset of users which are possible collaborators for a specific project,
    which are not already collaborators."""
    existing_collaborators_user_ids = (ProjectCollaborator.objects.filter(project=project)
                                       .values_list('collaborator', flat=True))
    type_user_only = User.objects.filter(user_type=User.TYPE_USER)
    return type_user_only.exclude(Q(pk=user.pk) | Q(pk__in=existing_collaborators_user_ids))


def get_possible_members_of_organization(user, organization):
    """Return a queryset of users which are possible members for a specific organization,
    which are not already members."""
    existing_members_user_ids = (OrganizationMember.objects.filter(organization=organization)
                                 .values_list('member', flat=True))
    type_user_only = User.objects.filter(user_type=User.TYPE_USER)
    return type_user_only.exclude(Q(pk=organization.organization_owner.pk) | Q(pk__in=existing_members_user_ids))
