from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model

from rest_framework import permissions

from qfieldcloud.core.models import (
    Project, ProjectCollaborator, OrganizationMember,
    Organization)

User = get_user_model()


class FilePermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'projectid' not in request.parser_context['kwargs']:
            return False

        project_id = request.parser_context['kwargs']['projectid']

        try:
            project = Project.objects.get(id=project_id)
        except ObjectDoesNotExist:
            return False

        # The owner can do anything
        if request.user == project.owner:
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


class ListCreateProjectPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'owner' not in request.parser_context['kwargs']:
            return False

        request_owner = request.parser_context['kwargs']['owner']
        try:
            owner = User.objects.get(username=request_owner)
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


class ProjectPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'projectid' not in request.parser_context['kwargs']:
            return False
        else:
            project_id = request.parser_context['kwargs']['projectid']

        try:
            project = Project.objects.get(id=project_id)
        except ObjectDoesNotExist:
            return False

        # The owner can do anything
        if request.user == project.owner:
            return True

        member = None
        try:
            member = OrganizationMember.objects.get(
                organization=project.owner, member=request.user)
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


class IsProjectOwner(permissions.BasePermission):

    def has_permission(self, request, view):

        # Get the owner specified into the request or use
        # the user that did the request if the owner is not
        # specified
        owner = request.data.get('owner', request.user.username)
        owner_obj = User.objects.get(username=owner)

        return request.user == owner_obj

    def has_object_permission(self, request, view, obj):
        owner_obj = obj.owner

        return request.user == owner_obj


class IsOrganizationAdmin(permissions.BasePermission):

    def has_permission(self, request, view):

        # Get the owner specified into the request or use
        # the user that did the request if the owner is not
        # specified
        owner = request.data.get('owner', request.user.username)
        owner_obj = User.objects.get(username=owner)

        return OrganizationMember.objects.filter(
            organization=owner_obj,
            member=request.user,
            role=OrganizationMember.ROLE_ADMIN).exists()

    def has_object_permission(self, request, view, obj):
        owner_obj = obj.owner

        return OrganizationMember.objects.filter(
            organization=owner_obj,
            member=request.user,
            role=OrganizationMember.ROLE_ADMIN).exists()


class IsOrganizationMember(permissions.BasePermission):

    def has_permission(self, request, view):

        # Get the owner specified into the request or use
        # the user that did the request if the owner is not
        # specified
        owner = request.data.get('owner', request.user)
        owner_obj = User.objects.get(username=owner)

        return OrganizationMember.objects.filter(
            organization=owner_obj,
            member=request.user,
            role=OrganizationMember.ROLE_MEMBER).exists()

    def has_object_permission(self, request, view, obj):
        owner_obj = obj.owner

        if request.user == owner_obj:
            return True

        return OrganizationMember.objects.filter(
            organization=owner_obj,
            member=request.user,
            role=OrganizationMember.ROLE_ADMIN).exists()


class IsProjectCollaboratorAdmin(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        ProjectCollaborator.objects.filter(
            project=obj,
            collaborator=request.user,
            role=ProjectCollaborator.ROLE_ADMIN).exists()


class IsProjectCollaboratorManager(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        ProjectCollaborator.objects.filter(
            project=obj,
            collaborator=request.user,
            role=ProjectCollaborator.ROLE_MANAGER).exists()


class IsProjectCollaboratorEditor(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        ProjectCollaborator.objects.filter(
            project=obj,
            collaborator=request.user,
            role=ProjectCollaborator.ROLE_EDITOR).exists()


class IsProjectCollaboratorReporter(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        ProjectCollaborator.objects.filter(
            project=obj,
            collaborator=request.user,
            role=ProjectCollaborator.ROLE_REPORTER).exists()


class IsProjectCollaboratorReader(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        ProjectCollaborator.objects.filter(
            project=obj,
            collaborator=request.user,
            role=ProjectCollaborator.ROLE_READER).exists()


class UserPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'username' not in request.parser_context['kwargs']:
            return False

        request_username = request.parser_context['kwargs']['username']
        try:
            user = User.objects.get(username=request_username)
        except ObjectDoesNotExist:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True
        elif request.user == user:
            return True
        else:
            return False


class OrganizationPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'organization' not in request.parser_context['kwargs']:
            return False

        organization_request = request.parser_context['kwargs']['organization']
        try:
            organization_owner = Organization.objects.get(
                username=organization_request).organization_owner
        except ObjectDoesNotExist:
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        # The owner can do anything
        if request.user == organization_owner:
            return True

        try:
            organization_member = OrganizationMember.objects.get(
                member=request.user)
        except ObjectDoesNotExist:
            return False

        if organization_member.role == organization_member.ROLE_ADMIN:
            return True


class CollaboratorPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        if 'projectid' not in request.parser_context['kwargs']:
            return False
        else:
            project_id = request.parser_context['kwargs']['projectid']

        try:
            project = Project.objects.get(id=project_id)
        except ObjectDoesNotExist:
            return False

        # The owner can do anything
        if request.user == project.owner:
            return True

        member = None
        try:
            member = OrganizationMember.objects.get(
                organization=project.owner, member=request.user)
        except ObjectDoesNotExist:
            pass

        if member == OrganizationMember.ROLE_ADMIN:
            return True

        collaborator = None
        try:
            collaborator = ProjectCollaborator.objects.get(
                project=project, collaborator=request.user)
        except ObjectDoesNotExist:
            return False

        if request.method in permissions.SAFE_METHODS:
            return collaborator.role in [
                ProjectCollaborator.ROLE_ADMIN,
                ProjectCollaborator.ROLE_MANAGER,
                ProjectCollaborator.ROLE_EDITOR,
                ProjectCollaborator.ROLE_REPORTER,
                ProjectCollaborator.ROLE_READER]
        else:
            return collaborator.role in [
                ProjectCollaborator.ROLE_ADMIN,
                ProjectCollaborator.ROLE_MANAGER]
