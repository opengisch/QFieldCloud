from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from invitations.utils import get_invitation_model
from qfieldcloud.core.invitations_utils import is_valid_email, send_invitation


class Command(BaseCommand):
    """
    Invite one or more users using the CLI.
    """

    help = """
        Create a user with given username, email and password
        Usage: python manage.py createuser --username=user1 --emails=test1@test.com test2@test.com --exit-on-failure
    """

    def add_arguments(self, parser):
        parser.add_argument("--inviter", type=str, required=True)
        parser.add_argument("--emails", type=str, nargs="+", required=True)
        parser.add_argument("--exit-on-failure", action="store_true")

    def handle(self, *args, **options):
        User = get_user_model()
        Invitation = get_invitation_model()

        inviter_username = options.get("inviter")
        emails = options.get("emails", [])
        exit_on_failure = options.get("exit-on-failure")

        try:
            inviter = User.objects.get(username=inviter_username)
        except User.DoesNotExist:
            print(f'ERROR: Failed to find user "{inviter_username}"!')
            exit(1)

        invite = None
        is_invited = False

        for email in emails:
            if is_valid_email(email):
                qs = Invitation.objects.filter(email=email)

                if len(qs) > 0:
                    assert len(qs) == 1

                    if qs[0].key_expired():
                        qs.delete()
                    else:
                        print(f"WARNING: {email} has already been invited.")
                        continue

                if not is_invited:
                    invite = Invitation.create(email, inviter=inviter)

                if invite:
                    try:
                        send_invitation(invite)
                        print(f"Sent invitation to {email}")
                    except Exception as err:
                        print(f"ERROR: Failed sending an invitation: {err}")
                        invite = None
            else:
                print(f"ERROR: Invalid email address: {email}")

            if not invite:
                if exit_on_failure:
                    exit(1)
