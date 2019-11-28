from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Project, Collaborator

# TODO: rename the module to permission_utils?


def get_key_from_value(value):
    """Return the key from the role value
    e.g. return 'admin' for 1"""

    return dict(zip(settings.PERMISSION_ROLE.values(),
                    settings.PERMISSION_ROLE.keys()))[value]


def can_read(username, project_name):
    """Return True if user can read, write, admin,  own the project
    or the project is public otherwise return False"""

    if is_owner(username, project_name):
        return True

    if can_admin(username, project_name):
        return True

    if can_write(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if Collaborator.objects.filter(
            user=user, project=project,
            role=settings.PERMISSION_ROLE['read']):
        return True

    if not project.private:
        return True

    return False


def can_write(username, project_name):
    """Return True if user can write, admin or own the project
    otherwise return False"""

    if is_owner(username, project_name):
        return True

    if can_admin(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if Collaborator.objects.filter(
            user=user, project=project,
            role=settings.PERMISSION_ROLE['write']):
        return True

    return False


def can_admin(username, project_name):
    """Return True if the user can admin or own the project
    otherwise return False"""

    if is_owner(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if Collaborator.objects.filter(
            user=user, project=project,
            role=settings.PERMISSION_ROLE['admin']):
        return True

    return False


def is_owner(username, project_name):
    """Return True if the user is the owner of the project
    otherwise return False"""

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    return project.owner == user
