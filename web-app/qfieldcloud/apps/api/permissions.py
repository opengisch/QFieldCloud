from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model

from rest_framework import permissions

from qfieldcloud.apps.model.models import (
    Project, ProjectCollaborator, OrganizationMember)


class FilePermission(permissions.BasePermission):

    def has_permission(self, request, view):
        request_project = request.parser_context['kwargs']['project']
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
            project = Project.objects.get(name=request_project, owner=owner)
        except ObjectDoesNotExist:
            return False

        # The owner can do anything
        if request.user == owner:
            return True

        collaborator = None
        try:
            collaborator = ProjectCollaborator.objects.get(
                project=project, collaborator=request.user)
        except ObjectDoesNotExist:
            pass

        if request.method == 'GET' and not collaborator:
            return not project.private
        elif request.method == 'GET' and collaborator:
            return collaborator.role in [
                ProjectCollaborator.ROLE_ADMIN,
                ProjectCollaborator.ROLE_MANAGER,
                ProjectCollaborator.ROLE_EDITOR,
                ProjectCollaborator.ROLE_REPORTER,
                ProjectCollaborator.ROLE_READER]
        elif request.method == 'POST' and collaborator:
            return collaborator.role in [
                ProjectCollaborator.ROLE_ADMIN,
                ProjectCollaborator.ROLE_MANAGER,
                ProjectCollaborator.ROLE_EDITOR,
                ProjectCollaborator.ROLE_REPORTER]
        elif request.method == 'DELETE':
            return collaborator.role in [
                ProjectCollaborator.ROLE_ADMIN,
                ProjectCollaborator.ROLE_MANAGER,
                ProjectCollaborator.ROLE_EDITOR]
        else:
            return False


class ProjectPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = get_user_model().objects.get(username=request_owner)
        except ObjectDoesNotExist:
            return False

        # The owner can do anything
        if request.user == owner:
            return True

        member = None
        try:
            member = OrganizationMember.objects.get(
                organization=owner, member=request.user)
        except ObjectDoesNotExist:
            pass

        if request.method == 'GET':
            return True
        elif request.method == 'POST' and member:
            return member == OrganizationMember.ROLE_ADMIN
        elif request.method == 'DELETE' and member:
            return member == OrganizationMember.ROLE_ADMIN
        else:
            return False


class OrganizationPermission(permissions.BasePermission):
    # TODO: implement
    pass
