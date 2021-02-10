from django.contrib.auth import get_user_model

from qfieldcloud.core.models import (
    ProjectCollaborator, OrganizationMember,
    Organization)

User = get_user_model()


def _is_project_owner(user, project):
    return project.owner == user


def _is_project_collaborator_role_admin(user, project):
    # An owner is always admin
    if _is_project_owner(user, project):
        return True

    return ProjectCollaborator.objects.filter(
        project=project,
        collaborator=user,
        role=ProjectCollaborator.ROLE_ADMIN).exists()


def _is_project_collaborator_role_manager(user, project):
    return ProjectCollaborator.objects.filter(
        project=project,
        collaborator=user,
        role=ProjectCollaborator.ROLE_MANAGER).exists()


def _is_project_collaborator_role_editor(user, project):
    return ProjectCollaborator.objects.filter(
        project=project,
        collaborator=user,
        role=ProjectCollaborator.ROLE_EDITOR).exists()


def _is_project_collaborator_role_reporter(user, project):
    return ProjectCollaborator.objects.filter(
        project=project,
        collaborator=user,
        role=ProjectCollaborator.ROLE_REPORTER).exists()


def _is_project_collaborator_role_reader(user, project):
    return ProjectCollaborator.objects.filter(
        project=project,
        collaborator=user,
        role=ProjectCollaborator.ROLE_READER).exists()


def _is_organization_owner(user, organization):
    if organization == user:
        return True
    if organization.user_type == Organization.TYPE_ORGANIZATION:
        # To be sure we didn't receive a User object instead of an
        # Organization one
        if type(organization) == User:
            organization = Organization.objects.get(
                username=organization.username)
        return organization.organization_owner == user
    return False


def _is_organization_member_role_admin(user, organization):
    # An owner is always admin
    if _is_organization_owner(user, organization):
        return True

    return OrganizationMember.objects.filter(
        organization=organization,
        member=user,
        role=OrganizationMember.ROLE_ADMIN).exists()


def _is_organization_member_role_member(user, organization):
    return OrganizationMember.objects.filter(
        organization=organization,
        member=user,
        role=OrganizationMember.ROLE_MEMBER).exists()


def get_param_from_request(request, param):
    """Try to get the param from the request data or the request
    context, returns None otherwise"""

    result = request.data.get(param, None)
    if not result:
        result = request.parser_context['kwargs'].get(param, None)
    return result


def can_create_project(user, organization=None):
    """Return True if the `user` can create a project. Accepts additional
    `organizaiton` to check whether the user has permissions to do so on
    that organization. Return False otherwise."""

    if organization is None:
        return True
    if user == organization:
        return True
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_update_delete_project(user, project):
    """Return True if the `user` can update or delete `project`.
    Return False otherwise."""

    if _is_project_owner(user, project):
        return True
    if _is_project_collaborator_role_admin(user, project):
        return True

    organization = project.owner
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_get_project(user, project):
    """Return True if the `user` can get `project`.
    Return False otherwise."""

    if not project.private:
        return True
    if can_update_delete_project(user, project):
        return True
    if _is_project_collaborator_role_manager(user, project):
        return True
    if _is_project_collaborator_role_editor(user, project):
        return True
    if _is_project_collaborator_role_reporter(user, project):
        return True
    return False


def can_list_files(user, project):
    """Return True if the `user` can list the files in `project`.
    Return False otherwise."""

    if not project.private:
        return True
    if _is_project_owner(user, project):
        return True
    if _is_project_collaborator_role_admin(user, project):
        return True
    if _is_project_collaborator_role_manager(user, project):
        return True
    if _is_project_collaborator_role_editor(user, project):
        return True
    if _is_project_collaborator_role_reporter(user, project):
        return True
    if _is_project_collaborator_role_reader(user, project):
        return True

    organization = project.owner
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_delete_files(user, project):
    """Return True if the `user` can delete files in `project`.
    Return False otherwise."""

    if _is_project_owner(user, project):
        return True
    if _is_project_collaborator_role_admin(user, project):
        return True
    if _is_project_collaborator_role_manager(user, project):
        return True
    if _is_project_collaborator_role_editor(user, project):
        return True

    organization = project.owner
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_upload_files(user, project):
    """Return True if the `user` can upload files to `project`.
    Return False otherwise."""

    if can_delete_files(user, project):
        return True
    if _is_project_collaborator_role_reporter(user, project):
        return True
    return False


def can_download_files(user, project):
    """Return True if the `user` can download files from `project`.
    Return False otherwise."""

    if can_upload_files(user, project):
        return True
    if _is_project_collaborator_role_reader(user, project):
        return True
    return False


def can_upload_deltas(user, project):
    """Return True if the `user` upload deltafiles in `project`.
    Return False otherwise."""

    return can_upload_files(user, project)


def can_list_deltas(user, project):
    """Return True if the `user` can list deltafiles of `project`.
    Return False otherwise."""
    if not project.private:
        return True

    return can_upload_deltas(user, project)


def can_list_users_organizations(user):
    """Return True if the `user` can list users and orgnizations.
    Return False otherwise."""

    return True


def can_update_user(request_maker_user, user):
    """Return True if the `request_maker_user` can update details of `user`.
    Return False otherwise."""

    if request_maker_user == user:
        return True

    if not _is_organization_member_role_admin(request_maker_user, user):
        return False

    return True


def can_list_collaborators(user, project):
    """Return True if the `user` can list collaborators of `project`.
    Return False otherwise."""

    return True


def can_create_collaborators(user, project):
    """Return True if the `user` can create collaborators of `project`.
    Return False otherwise."""

    if _is_project_owner(user, project):
        return True
    if _is_project_collaborator_role_admin(user, project):
        return True
    if _is_project_collaborator_role_manager(user, project):
        return True
    if _is_project_collaborator_role_editor(user, project):
        return True

    organization = project.owner
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_update_delete_collaborators(user, project):
    """Return True if the `user` can update or delete collaborators of
    `project`. Return False otherwise."""

    return can_create_collaborators(user, project)


def can_update_collaborator_role(user, project, collaborator):
    """Return True if the `user` can create update the `collaborator`
    role of `project`. Return False otherwise."""

    return can_create_collaborators(user, project)


def can_delete_collaborator(user, project, collaborator):
    """Return True if the `user` can delete the `collaborator` of `project`.
    Return False otherwise."""

    return can_update_collaborator_role(user, project, collaborator)


def can_get_collaborator_role(user, project, collaborator):
    """Return True if the `user` can create get the role of `collaborator`
    of `project`. Return False otherwise."""

    return True


def can_list_members(user, organization):
    """Return True if the `user` can list members of `organization`.
    Return False otherwise."""

    return True


def can_create_members(user, organization):
    """Return True if the `user` can create members of `organization`.
    Return False otherwise."""

    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_update_member_role(user, organization, member):
    """Return True if the `user` can update `member` of `organization`.
    Return False otherwise."""

    return can_create_members(user, organization)


def can_delete_member_role(user, organization, member):
    """Return True if the `user` can delete `member` of `organization`.
    Return False otherwise."""

    return can_update_member_role(user, organization, member)


def can_get_member_role(user, organization, member):
    """Return True if the `user` can get `member` of `organization`.
    Return False otherwise."""

    return True


def can_become_collaborator(user, project):
    """Return True if the `user` can list the files in `project`.
    Return False otherwise."""

    if _is_project_owner(user, project):
        return False
    if _is_project_collaborator_role_admin(user, project):
        return False
    if _is_project_collaborator_role_manager(user, project):
        return False
    if _is_project_collaborator_role_editor(user, project):
        return False
    if _is_project_collaborator_role_reporter(user, project):
        return False
    if _is_project_collaborator_role_reader(user, project):
        return False

    organization = project.owner
    if _is_organization_owner(user, organization):
        return False
    if _is_organization_member_role_admin(user, organization):
        return False

    return True


def can_create_geodb(user, profile):
    if profile.has_geodb:
        return False

    if not can_update_user(user, profile):
        return False

    return True


def can_become_member(user, organization):
    if _is_organization_member_role_admin(user, organization):
        return False
    if _is_organization_member_role_member(user, organization):
        return False

    return True
