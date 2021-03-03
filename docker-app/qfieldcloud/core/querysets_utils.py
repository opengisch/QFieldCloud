from django.db.models import Q, Count
from django.db.models.expressions import Case, F, Value, When
from django.db.models.fields import CharField
from django.db.models.manager import BaseManager
from django.db.models.query import QuerySet

from qfieldcloud.core.models import (
    Project, ProjectCollaborator, OrganizationMember,
    Organization, Delta, User)


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
    queryset = queryset.annotate(collaborators__count=Count('collaborators'))
    queryset = queryset.annotate(deltas__count=Count('deltas'))
    queryset = queryset.annotate(collaborators__role=Case(
        When(collaborators__collaborator=user, then=F('collaborators__role'))
    ))
    queryset = queryset.annotate(collaborators__role=Case(
        When(collaborators__role=1, then=Value('admin', output_field=CharField())),
        When(collaborators__role=2, then=Value('manager', output_field=CharField())),
        When(collaborators__role=3, then=Value('editor', output_field=CharField())),
        When(collaborators__role=4, then=Value('reporter', output_field=CharField())),
        When(collaborators__role=5, then=Value('reader', output_field=CharField())),
    ))

    queryset.order_by('owner__username', 'name')

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


def get_user_organizations(user: User, administered_only: bool = False) -> QuerySet:
    owned_organizations = Organization.objects.filter(organization_owner=user).distinct()
    memberships = OrganizationMember.objects.filter(member=user)

    if administered_only:
        memberships = memberships.filter(role=OrganizationMember.ROLE_ADMIN)

    membership_organizations = Organization.objects.filter(members__in=memberships)
    organizations = owned_organizations.union(membership_organizations)

    return organizations


def get_organization_members(organization):
    return OrganizationMember.objects.filter(organization=organization)


def get_all_public_projects():
    """Return all public projects."""
    return Project.objects.filter(private=False)


def get_deltas_of_project(project):
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
) -> BaseManager:
    assert project is None or organization is None, 'Cannot have the project and organization filters set simultaneously'

    if username:
        users = User.objects.filter(Q(username__icontains=username) | Q(email__icontains=username))
    else:
        users = User.objects.all()

    if exclude_organizations:
        users = users.filter(user_type=User.TYPE_USER)

    # exclude the already existing collaborators and the project owner
    if project:
        collaborator_ids = ProjectCollaborator.objects.filter(project=project).values_list('collaborator', flat=True)
        users = users.exclude(pk__in=collaborator_ids)
        users = users.exclude(pk=project.owner.pk)

    # exclude the already existing members, the organization owner and the organization itself from the returned users
    if organization:
        member_ids = OrganizationMember.objects.filter(organization=organization).values_list('member', flat=True)
        users = users.exclude(pk__in=member_ids)
        users = users.exclude(pk=organization.organization_owner.pk)
        users = users.exclude(pk=organization.user_ptr.pk)

    return users.order_by('-username')
