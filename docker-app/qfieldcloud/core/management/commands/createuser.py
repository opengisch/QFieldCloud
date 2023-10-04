from django.core.management.base import BaseCommand
from qfieldcloud.core.models import Person


class Command(BaseCommand):
    """
    Creates a normal or super user using the CLI.
    Unlike the Django's createsuperuser command, here we can pass the password as an argument.
    This is a utility function that is expected to be used only for testing purposes.
    """

    help = """
        Create a user with given username, email and password
        Usage: python manage.py createuser --username=test --email=test@test.com --password=test --superuser
    """

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, required=True)
        parser.add_argument("--password", type=str, required=True)
        parser.add_argument("--email", type=str, required=True)
        parser.add_argument("--superuser", action="store_true")

    def handle(self, *args, **options):
        username = options.get("username")
        password = options.get("password")
        email = options.get("email")
        is_superuser = options.get("superuser")
        try:
            if not Person.objects.filter(username=username).exists():
                Person.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_superuser=is_superuser,
                )
                print(f"User {username} has been successfully created\n")
            else:
                print(f"User {username} already exists\n")
        except Exception as e:
            print("ERROR: Unable to create user\n%s\n" % e)
            exit(1)
