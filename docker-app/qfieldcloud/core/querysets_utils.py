from qfieldcloud.core.models import (
    Project, ProjectCollaborator)


def get_available_projects(user, include_public=False):
    """Return a queryset with all projects that are available to the `user`.
    The param `user` is meant to be the user that did the request"""

    queryset = (Project.objects.filter(
        owner=user) | Project.objects.filter(
            collaborators__in=ProjectCollaborator.objects.filter(
                collaborator=user))).distinct()

    if include_public:
        queryset |= Project.objects.filter(private=False).distinct()

    return queryset


def get_projects_of_owner(user, owner):
    """Return a queryset with all the projects of `owner` that
    are visible to `user`. The param `user` is meant to be the
    user that did the request"""

    if owner == user:
        return Project.objects.filter(owner=owner)

    queryset = (Project.objects.filter(
        owner=owner,
        collaborators__in=ProjectCollaborator.objects.filter(
            collaborator=user))).distinct()

    queryset |= Project.objects.filter(owner=owner, private=False).distinct()

    return queryset
