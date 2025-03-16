from axes.signals import user_locked_out
from django.dispatch import receiver

from qfieldcloud.core.exceptions import TooManyLoginAttemptsError


@receiver(user_locked_out)
def raise_permission_denied(*args, **kwargs):
    raise TooManyLoginAttemptsError()
