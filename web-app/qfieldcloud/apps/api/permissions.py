from django.conf import settings
from django.contrib.auth import get_user_model

from rest_framework import permissions

from qfieldcloud.apps.model.models import (
    Project,
    #ProjectRole
)

class IsProjectOwner(permissions.BasePermission):

    def has_permission(self, request, view):
        print("has permission: {} {}".format(request, view))
        return True

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        print("isProjectOwner: {} {} {}".format(request, view, obj))
        return True


class IsProjectAdmin(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsProjectManagerOrHigher(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsProjectEditorOrHigher(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsProjectReporterOrHigher(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsProjectReaderOrHigher(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsOrganizationAdmin(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsOrganizationMemberOrHigher(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


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

    #if ProjectRole.objects.filter(
    #        user=user, project=project,
    #        role=settings.PROJECT_ROLE['admin']):
    #    return True

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

    #if ProjectRole.objects.filter(
    #        user=user, project=project,
    #        role=settings.PROJECT_ROLE['manager']):
    #    return True

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

    #if ProjectRole.objects.filter(
    #        user=user, project=project,
    #        role=settings.PROJECT_ROLE['editor']):
    #    return True

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

    #if ProjectRole.objects.filter(
    #        user=user, project=project,
    #        role=settings.PROJECT_ROLE['reporter']):
    #    return True

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

    #if ProjectRole.objects.filter(
    #        user=user, project=project,
    #        role=settings.PROJECT_ROLE['reader']):
    #    return True

    return False
