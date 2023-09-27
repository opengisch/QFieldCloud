from django.contrib.auth.management.commands.createsuperuser import (
    Command as SuperUserCommand,
)
from qfieldcloud.core.models import Person


class Command(SuperUserCommand):
    """
    We overwrite the django createsuperuser command because it uses the wrong User model
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.UserModel = Person
