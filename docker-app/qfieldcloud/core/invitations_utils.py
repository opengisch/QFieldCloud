import logging

from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from invitations.adapters import get_invitations_adapter
from invitations.signals import invite_url_sent
from invitations.utils import get_invitation_model

from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import Person

logger = logging.getLogger(__name__)


def is_valid_email(email: str) -> bool:
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


def invite_user_by_email(
    email: str, inviter: Person, send: bool = True
) -> tuple[bool, str]:
    """
    Sends an invite for a given email address

    Args :
        email:      recipient's email
        inviter:    inviter
        send:       whether the email should be sent

    Returns :
        (bool, str) success, message
    """

    try:
        validate_email(email)
    except ValidationError:
        return False, _(
            "The provided email address is not valid. Users can only be invited with a valid email address."
        )

    if not permissions_utils.can_send_invitations(inviter, inviter):
        return False, _("Your user cannot send invitations.")

    Invitation = get_invitation_model()
    Invitation.objects.filter(email=email, sent__isnull=True).delete()
    qs = Invitation.objects.filter(email=email)

    if len(qs) > 0:
        invite = qs[0]

        assert len(qs) == 1

        if invite.key_expired():
            qs.delete()
        else:
            return (
                False,
                _(
                    "{} has already been invited to create a QFieldCloud account."
                ).format(email),
            )

    qs = Person.objects.filter(email=email)

    if len(qs) > 0:
        assert len(qs) == 1

        return (
            False,
            _("{} has already been used by a registered QFieldCloud user.").format(
                email
            ),
        )

    invite = Invitation.create(email, inviter=inviter)

    # TODO see if we can "pre-attach" this future user to this project, probably to be done
    # at the same time as TODO below about actual invitation
    if send and inviter.remaining_invitations > 0:
        inviter.remaining_invitations -= 1
        inviter.save()
        send_invitation(invite)
        return (
            True,
            _("{} has been invited to create a QFieldCloud account.").format(email),
        )

    return True, _("{} has been added to the QFieldCloud waiting list.").format(email)


def send_invitation(invite, **kwargs):
    """Sends invitation.

    Args:
        invite: the invitation to be sent

    The same as the original Invitation.send_invitation, but without passing the request object.
    https://github.com/bee-keeper/django-invitations/blob/invitations/models.py#L42
    """
    current_site = kwargs.pop("site", Site.objects.get_current())
    invite_url = reverse("invitations:accept-invite", args=[invite.key])
    invite_url = f"https://{current_site.domain}{invite_url}"
    ctx = kwargs
    ctx.update(
        {
            "invite_url": invite_url,
            "site_name": current_site.name,
            "email": invite.email,
            "key": invite.key,
            "inviter": invite.inviter,
        }
    )

    email_template = "invitations/email/email_invite"

    get_invitations_adapter().send_mail(
        email_template,
        invite.email,
        ctx,
    )
    invite.sent = timezone.now()
    invite.save()

    invite_url_sent.send(
        sender=invite.__class__,
        instance=invite,
        invite_url_sent=invite_url,
        inviter=invite.inviter,
    )
