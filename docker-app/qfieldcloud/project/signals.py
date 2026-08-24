import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from qfieldcloud.core.exceptions import UnexpectedProjectCollaboratorError
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    ProjectCollaborator,
)
from qfieldcloud.project.enums import ProjectCollaboratorRole
from qfieldcloud.project.models import Project

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Project)
def grant_creator_organization_project_admin_access(
    sender, instance, created, **kwargs
):
    """
    Whenever an organization-owned project is created by someone without
    project-admin access, give them explicit `ADMIN` collaborator role.

    Organization owners and `ADMIN` organization members already get project-admin access
    via `projects_with_roles_vw` and don't need to be added as collaborator.
    """
    # We want to add `ADMIN` collaborator only on creation
    if not created:
        return

    # We use the `created_by` to determine the `ADMIN` collaborator to add, if missed we cannot do much besides logging
    if instance.created_by is None:
        logger.warning(
            'Project "%s" created but `created_by` field is empty!', instance.name
        )

        return

    # For now we want to add an `ADMIN` collaborator only if the project owner is an organization
    if not instance.owner.is_organization:
        return

    organization = Organization.objects.get(pk=instance.owner.pk)

    # Skip adding `ADMIN` collaborator if the user is the organization owner, because
    # they already have `ADMIN` access through the organization.
    if instance.created_by == organization.organization_owner:
        return

    try:
        member_role = OrganizationMember.objects.get(
            organization=organization,
            member=instance.created_by,
        ).role
    except OrganizationMember.DoesNotExist:
        member_role = None

    # When the user already has `ADMIN` organization membership, no need to add them as collaborator.
    if member_role == OrganizationMember.Roles.ADMIN:
        return

    # For now we only support creating projects by `ADMIN` and `CREATOR` organization members
    if member_role != OrganizationMember.Roles.CREATOR:
        raise NotImplementedError(
            "Only roles `ADMIN` and `CREATOR` organization members can create projects within an organization, but {} role given!".format(
                member_role
            )
        )

    # Since it is a completely new project, the current user should not be already a collaborator. If they are a collaborator, we should raise and cancel the operation.
    if ProjectCollaborator.objects.filter(
        project=instance,
        collaborator=instance.created_by,
    ).exists():
        raise UnexpectedProjectCollaboratorError()

    # Finally add the user as an `ADMIN` collaborator to the project.
    ProjectCollaborator.objects.create(
        project=instance,
        collaborator=instance.created_by,
        role=ProjectCollaboratorRole.ADMIN,
        created_by=instance.created_by,
        updated_by=instance.created_by,
    )
