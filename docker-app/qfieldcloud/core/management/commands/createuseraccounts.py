from django.core.management.base import BaseCommand
from qfieldcloud.core.models import User, UserAccount


class Command(BaseCommand):
    """
    Creates user accounts for all users that are missing a user account.
    """

    def handle(self, *args, **options):
        for user in User.objects.filter(
            useraccount=None,
            type__in=[User.Type.PERSON, User.Type.ORGANIZATION],
        ):
            print(
                f'Creating user account for user "{user.username}" email "{user.email}"...'
            )
            UserAccount.objects.create(user=user)
