from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


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
