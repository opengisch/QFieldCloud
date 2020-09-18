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


def can_create_project(user, organization):
    if user == organization:
        return True
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_update_delete_project(user, project):
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
    if can_delete_files(user, project):
        return True
    if _is_project_collaborator_role_reporter(user, project):
        return True
    return False


def can_download_files(user, project):
    if can_upload_files(user, project):
        return True
    if _is_project_collaborator_role_reader(user, project):
        return True
    return False


def can_upload_deltas(user, project):
    return can_upload_files(user, project)


def can_list_deltas(user, project):
    return can_upload_deltas(user, project)


def can_list_users_organizations(user):
    return True


def can_update_user(request_maker_user, user):
    if request_maker_user == user:
        return True


def can_list_collaborators(user, project):
    return True


def can_create_collaborators(user, project):
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


def can_update_collaborator_role(user, project, collaborator):
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


def can_delete_collaborator(user, project, collaborator):
    return can_update_collaborator_role(user, project, collaborator)


def can_get_collaborator_role(user, project, collaborator):
    return True


def can_list_members(user, organization):
    return True


def can_create_members(user, organization):
    if _is_organization_owner(user, organization):
        return True
    if _is_organization_member_role_admin(user, organization):
        return True
    return False


def can_update_member_role(user, organization, member):
    return can_create_members(user, organization)


def can_delete_member_role(user, organization, member):
    return can_update_member_role(user, organization, member)


def can_get_member_role(user, organization, member):
    return True
