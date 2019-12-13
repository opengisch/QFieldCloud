from django.conf import settings
from django.contrib.auth import get_user_model

from .models import Project, ProjectRole, OrganizationRole

# TODO: rename the module to permission_utils?


def get_key_from_value(value):
    """Return the key from the role value
    e.g. return 'admin' for 1"""

    return dict(zip(settings.PROJECT_ROLE.values(),
                    settings.PROJECT_ROLE.keys()))[value]


def is_project_owner(username, project_name):
    """Return True if the user is the owner of the project
    otherwise return False"""

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    return project.owner == user


def is_project_admin(username, project_name):
    """Return True if the user is admin or owner of the project
    otherwise return False"""

    if is_project_owner(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if ProjectRole.objects.filter(
            user=user, project=project,
            role=settings.PROJECT_ROLE['admin']):
        return True

    return False


def is_project_manager(username, project_name):
    """Return True if user is manager, admin or own the project
    otherwise return False"""

    if is_project_owner(username, project_name):
        return True

    if is_project_admin(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if ProjectRole.objects.filter(
            user=user, project=project,
            role=settings.PROJECT_ROLE['manager']):
        return True

    return False


def is_project_editor(username, project_name):
    """Return True if user is editor, manager, admin or own the project
    otherwise return False"""

    if is_project_owner(username, project_name):
        return True

    if is_project_admin(username, project_name):
        return True

    if is_project_manager(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if ProjectRole.objects.filter(
            user=user, project=project,
            role=settings.PROJECT_ROLE['editor']):
        return True

    return False


def is_project_reporter(username, project_name):
    """Return True id user is reporter, editor, manager, admin or own the project
    otherwise return False"""

    if is_project_owner(username, project_name):
        return True

    if is_project_admin(username, project_name):
        return True

    if is_project_manager(username, project_name):
        return True

    if is_project_editor(username, project_name):
        return True

    project = Project.objects.get(name=project_name)
    user = get_user_model().objects.get(username=username)

    if ProjectRole.objects.filter(
            user=user, project=project,
            role=settings.PROJECT_ROLE['reporter']):
        return True

    return False


def is_project_reader(username, project_name):
    """Return True if user is reader, reporter, editor, manager, admin,
    own the project or the project is not private otherwise return False"""

    project = Project.objects.get(name=project_name)

    if not project.private:
        return True

    if is_project_owner(username, project_name):
        return True

    if is_project_admin(username, project_name):
        return True

    if is_project_manager(username, project_name):
        return True

    if is_project_editor(username, project_name):
        return True

    user = get_user_model().objects.get(username=username)

    if ProjectRole.objects.filter(
            user=user, project=project,
            role=settings.PROJECT_ROLE['reader']):
        return True

    return False


def is_organization_admin(username, organization_name):
    """Return True if the user is admin of the organizazion
    otherwise return False"""

    user = get_user_model().objects.get(username=username)
    organization = get_user_model().objects.get(username=organization_name)

    if OrganizationRole.objects.filter(
            user=user, organization=organization,
            role=settings.ORGANIZATION_ROLE['admin']):
        return True

    return False


def is_organization_member(username, organization_name):
    """Return True if the user is admin or member of the organizazion
    otherwise return False"""

    if is_organization_admin(username, organization_name):
        return True

    user = get_user_model().objects.get(username=username)
    organization = get_user_model().objects.get(username=organization_name)

    if OrganizationRole.objects.filter(
            user=user, organization=organization,
            role=settings.ORGANIZATION_ROLE['member']):
        return True

    return False
