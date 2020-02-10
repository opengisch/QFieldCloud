from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model

from rest_framework import permissions

from qfieldcloud.apps.model.models import (
    Project, ProjectCollaborator
)


class IsProjectOwner(permissions.BasePermission):

    def has_permission(self, request, view):
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
        except get_user_model().DoesNotExist:
            return False
        return request.user == owner


class IsProjectAdmin(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)

            ProjectCollaborator.objects.get(
                project=project, collaborator=request.user,
                role=ProjectCollaborator.ROLE_ADMIN
            )
        except ObjectDoesNotExist:
            return False

        return True


class IsProjectManager(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)

            ProjectCollaborator.objects.get(
                project=project, collaborator=request.user,
                role=ProjectCollaborator.ROLE_MANAGER
            )
        except ObjectDoesNotExist:
            return False

        return True


class IsProjectEditor(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)

            ProjectCollaborator.objects.get(
                project=project, collaborator=request.user,
                role=ProjectCollaborator.ROLE_EDITOR
            )
        except ObjectDoesNotExist:
            return False

        return True


class IsProjectReporter(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)

            ProjectCollaborator.objects.get(
                project=project, collaborator=request.user,
                role=ProjectCollaborator.ROLE_REPORTER
            )
        except ObjectDoesNotExist:
            return False

        return True


class IsProjectReader(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)

            ProjectCollaborator.objects.get(
                project=project, collaborator=request.user,
                role=ProjectCollaborator.ROLE_READER
            )
        except ObjectDoesNotExist:
            return False

        return True


class IsProjectPublic(permissions.BasePermission):
    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)
        except ObjectDoesNotExist:
            return False

        return not project.private

class IsOrganizationAdmin(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True


class IsOrganizationMember(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        # TODO: implement
        return True
