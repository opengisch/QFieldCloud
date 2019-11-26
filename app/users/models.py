from django.db import models
from django.contrib.auth.models import AbstractUser


USER_TYPE = (
    (1, 'user'),
    (2, 'organization'),
)


class User(AbstractUser):
    type = models.IntegerField(choices=USER_TYPE, default=1)

    REQUIRED_FIELDS = ['type', 'email']

    def __str__(self):
        return self.username
