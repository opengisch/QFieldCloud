"""
This module logs activity streams using the `django-activity-stream` package.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django_currentuser.middleware import get_current_authenticated_user
from notifications.signals import notify

from ..core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    ProjectQueryset,
    Team,
    TeamMember,
    User,
)


def _send_notif(verb, action_object, recipient, target=None):
    """
    Sends a notification through django-notifications, but sets it as already read
    if the actor is the same as the recipient
    """
    authenticated_user = get_current_authenticated_user()

    # django-notifications-hq doesn't support Anonymous users yet (e.g. management command)
    if authenticated_user is None:
        return

    # deduplicate
    recipient = list(set(recipient))

    if authenticated_user in recipient:
        # If the actor is already the recipient, we consider the notification as seen

        # TODO : marking notifications as read is currently not supported, so we disable
        # self-notifications for now
        # see https://github.com/django-notifications/django-notifications/issues/317
        # notify.send(
        #     authenticated_user,
        #     verb=verb,
        #     action_object=action_object,
        #     target=target,
        #     recipient=[authenticated_user],
        #     unread=False, # not supported !
        # )
        recipient.remove(authenticated_user)

    notify.send(
        authenticated_user,
        verb=verb,
        action_object=action_object,
        target=target,
        recipient=list(recipient),
    )


def _concerned_users_in_entity(entity: User):
    """Returns a list of users (of User.Type.PERSON) concerned by updates to an user (any type)"""

    return Person.objects.for_entity(entity)  # type: ignore


def _concerned_users_in_project(project: Project):
    """Returns a list of users concerned by updates to a project"""

    return Person.objects.for_project(project).exclude(  # type: ignore
        project_role_origin=ProjectQueryset.RoleOrigins.PUBLIC
    )


# Register signals
@receiver(post_save, sender=User)
def user_created(sender, instance, created, **kwargs):
    user = instance
    _send_notif(
        verb="created",
        action_object=user,
        recipient=_concerned_users_in_entity(user),
    )


# Organizations


@receiver(post_save, sender=Organization)
def organization_created(sender, instance, created, **kwargs):
    organization = instance
    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="created",
        action_object=organization,
        recipient=_concerned_users_in_entity(organization),
    )


@receiver(pre_delete, sender=Organization)
def organization_deleted(sender, instance, **kwargs):
    organization = instance

    _send_notif(
        verb="deleted",
        action_object=organization,
        recipient=_concerned_users_in_entity(organization),
    )


@receiver(post_save, sender=OrganizationMember)
def organization_membership_created(sender, instance, created, **kwargs):
    membership = instance
    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="added",
        action_object=membership.member,
        target=membership.organization,
        recipient=_concerned_users_in_entity(membership.organization),
    )


@receiver(pre_delete, sender=OrganizationMember)
def organization_membership_deleted(sender, instance, **kwargs):
    membership = instance
    _send_notif(
        verb="removed",
        action_object=membership.member,
        target=membership.organization,
        recipient=_concerned_users_in_entity(membership.organization),
    )


# Teams


@receiver(post_save, sender=Team)
def team_created(sender, instance, created, **kwargs):
    team = instance
    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="created",
        action_object=team,
        recipient=_concerned_users_in_entity(team),
    )


@receiver(pre_delete, sender=Team)
def team_deleted(sender, instance, **kwargs):
    team = instance
    _send_notif(
        verb="deleted",
        action_object=team,
        recipient=_concerned_users_in_entity(team),
    )


@receiver(post_save, sender=TeamMember)
def team_membership_created(sender, instance, created, **kwargs):
    membership = instance
    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="added",
        action_object=membership.member,
        target=membership.team,
        recipient=_concerned_users_in_entity(membership.team),
    )


@receiver(pre_delete, sender=TeamMember)
def team_membership_deleted(sender, instance, **kwargs):
    membership = instance
    _send_notif(
        verb="removed",
        action_object=membership.member,
        target=membership.team,
        recipient=_concerned_users_in_entity(membership.team),
    )


# Projects


@receiver(post_save, sender=Project)
def project_created(sender, instance, created, **kwargs):
    project = instance
    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="created",
        action_object=project,
        recipient=_concerned_users_in_project(project),
    )


@receiver(pre_delete, sender=Project)
def project_deleted(sender, instance, **kwargs):
    project = instance
    _send_notif(
        verb="deleted",
        action_object=project,
        recipient=_concerned_users_in_project(project),
    )


@receiver(post_save, sender=ProjectCollaborator)
def project_membership_created(sender, instance, created, **kwargs):
    membership = instance

    # We don't notify for simple updates
    if not created:
        return

    _send_notif(
        verb="added",
        action_object=membership.collaborator,
        target=membership.project,
        recipient=_concerned_users_in_project(membership.project),
    )


@receiver(pre_delete, sender=ProjectCollaborator)
def project_membership_deleted(sender, instance, **kwargs):
    membership = instance

    _send_notif(
        verb="removed",
        action_object=membership.collaborator,
        target=membership.project,
        recipient=_concerned_users_in_project(membership.project),
    )
