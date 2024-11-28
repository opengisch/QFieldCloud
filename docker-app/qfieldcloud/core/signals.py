from axes.signals import user_locked_out
from django.dispatch import receiver
from qfieldcloud.core.exceptions import TooManyLoginAttemptsError
from qfieldcloud.core.models import OrganizationMember, User
from django.db.models.signals import pre_delete


@receiver(user_locked_out)
def raise_permission_denied(*args, **kwargs):
    raise TooManyLoginAttemptsError()


@receiver(pre_delete, sender=User)
def update_project_owner_on_member_delete(sender, instance, **kwargs):
    """
    Update project ownership when an organization member is deleted.
    """

    try:
        org_membership = OrganizationMember.objects.get(member=instance)
    except OrganizationMember.DoesNotExist:
        return

    fallback_user = org_membership.organization.organization_owner
    OrganizationMember.objects.filter(created_by=instance).update(
        created_by=fallback_user
    )
    OrganizationMember.objects.filter(updated_by=instance).update(
        updated_by=fallback_user
    )
