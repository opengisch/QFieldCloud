from datetime import datetime

from django.core.management.base import BaseCommand
from qfieldcloud.core.invitations_utils import invite_user_by_email
from qfieldcloud.core.models import Person


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
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--emails", type=str, nargs="+", required=True)
        parser.add_argument("--exit-on-failure", action="store_true")

    def handle(self, *args, **options):
        inviter_username = options.get("inviter")
        emails = options.get("emails", [])
        exit_on_failure = options.get("exit-on-failure")
        sent_emails_limit = options.get("limit", 0)

        try:
            inviter = Person.objects.get(username=inviter_username)
        except Person.DoesNotExist:
            print(f'ERROR: Failed to find user "{inviter_username}"!')
            exit(1)

        sent_emails_count = 0

        for email in emails:
            if sent_emails_count >= sent_emails_limit:
                break

            success, message = invite_user_by_email(email, inviter)

            if success:
                sent_emails_count += 1
                print(
                    f"{datetime.now().isoformat()}\tSUCCESS\tinvitation sent to {email}."
                )
            else:
                print(
                    f"{datetime.now().isoformat()}\tWARNING\tinvitation not sent to {email}. {message}"
                )

                if exit_on_failure:
                    exit(1)
