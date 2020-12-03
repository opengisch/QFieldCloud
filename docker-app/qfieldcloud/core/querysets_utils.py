from qfieldcloud.core.models import (
    Project, ProjectCollaborator, OrganizationMember,
    Organization)


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
