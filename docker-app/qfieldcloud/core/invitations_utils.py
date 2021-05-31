import logging

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http.request import HttpRequest
from django.utils.translation import gettext as _
from invitations.utils import get_invitation_model
from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import User

logger = logging.getLogger(__name__)


def is_valid_email(email: str) -> bool:
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


def invite_user_by_email(
    email: str, request: HttpRequest, inviter: User = None, send: bool = True
) -> tuple:
    """
    Sends an invite for a given email address

    Args :
        email:      recipient's email
        request:    the request (used to build the absolute URL)
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

    if not inviter:
        inviter = request.user

    if not permissions_utils.can_send_invitations(inviter, inviter):
        return False, _("Your user cannot send invitations.")

    Invitation = get_invitation_model()
    Invitation.objects.filter(email=email, sent__isnull=True).delete()
    qs = Invitation.objects.filter(email=email)

    if len(qs) > 0:
        invite = qs[0]

        if invite.key_expired():
            qs.delete()
        else:
            return (
                False,
                _(
                    "{} has already been invited to create a QFieldCloud account."
                ).format(email),
            )

    invite = Invitation.create(email, inviter=inviter)

    # TODO see if we can "pre-attach" this future user to this project, probably to be done
    # at the same time as TODO below about actual invitation
    if send and inviter.remaining_invitations > 0:
        inviter.remaining_invitations -= 1
        inviter.save()
        invite.send_invitation(request)
        return (
            True,
            _("{} has been invited to create a QFieldCloud account.").format(email),
        )

    return True, _("{} has been added to the QFieldCloud waiting list.").format(email)
