from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext as _
from django.utils.translation import ngettext_lazy


def reserved_words_validator(value):
    reserved_words = [
        "user",
        "users",
        "project",
        "projects",
        "owner",
        "push",
        "file",
        "files",
        "collaborator",
        "collaborators",
        "member",
        "members",
        "organization",
        "qfield",
        "qfieldcloud",
        "history",
        "version",
        "delta",
        "deltas",
        "deltafile",
        "auth",
        "qfield-files",
        "esri",
    ]
    if value.lower() in reserved_words:
        raise ValidationError(_('"{}" is a reserved word!').format(value))


def file_storage_name_validator(value):
    if value not in settings.STORAGES:
        raise ValidationError(_("Storage {} is not a valid option!".format(value)))


@deconstructible
class MaxBytesLengthValidator(BaseValidator):
    message = ngettext_lazy(
        "Ensure this value has at most %(limit_value)d byte (it has %(show_value)d).",
        "Ensure this value has at most %(limit_value)d bytes (it has %(show_value)d).",
        "limit_value",
    )
    code = "max_length"

    def compare(self, a, b):
        return a > b

    def clean(self, x):
        return len(x.encode("utf-8"))
