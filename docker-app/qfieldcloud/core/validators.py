from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import BaseValidator
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext as _
from django.utils.translation import ngettext_lazy
from PIL import Image, UnidentifiedImageError


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
class MaxFileSizeValidator:
    def __init__(self, max_size_bytes: int):
        self.max_size_bytes = max_size_bytes

    def __call__(self, value):
        if value is None:
            return

        if value.size > self.max_size_bytes:
            raise ValidationError(
                _("File size must be under {} MB.").format(
                    self.max_size_bytes // (1024 * 1024)
                ),
                code="file_too_large",
            )


@deconstructible
class MaxImageDimensionValidator:
    def __init__(self, max_dimension_pixels: int):
        self.max_dimension_pixels = max_dimension_pixels

    def __call__(self, value):
        if value is None:
            return

        try:
            value.seek(0)
            with Image.open(value) as img:
                width, height = img.size

                if (
                    width > self.max_dimension_pixels
                    or height > self.max_dimension_pixels
                ):
                    raise ValidationError(
                        _("Max allowed size is {}px per dimension.").format(
                            self.max_dimension_pixels
                        ),
                        code="image_too_large",
                    )
        except (UnidentifiedImageError, OSError):
            raise ValidationError(
                _("Invalid image file."),
                code="invalid_image",
            )
        finally:
            value.seek(0)


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
