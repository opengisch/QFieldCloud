from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    """
    The standard django command to create superuser does not allow to pass the password as argument.
    With this command this is possible. Please use it only for testing purposes.
    """

    help = """
        Create a user with given username, email and password
        Usage: python manage.py createuser --username=test --email=test@test.com --password=test --superuser=True
    """

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, required=True)
        parser.add_argument('--password', type=str, required=True)
        parser.add_argument('--email', type=str, required=True)
        parser.add_argument('--superuser', type=bool, required=False, default=False)

    def handle(self, *args, **options):
        username = options.get('username')
        password = options.get('password')
        email = options.get('email')
        is_superuser = options.get('superuser')
        try:
            User = get_user_model()
            if not User.objects.filter(username=username).exists():
                User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_superuser=is_superuser,
                )
                print(f'User {username} has been successfully created\n')
            else:
                print(f'User {username} already exists\n')
        except Exception as e:
            print('ERROR: Unable to create user\n%s\n' % e)
            exit(1)
