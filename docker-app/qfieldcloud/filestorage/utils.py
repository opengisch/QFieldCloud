import hashlib
import re
import uuid
from pathlib import Path, PurePath
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

filename_validator = RegexValidator(
    settings.STORAGES_FILENAME_VALIDATION_REGEX,
    _(
        'The filename must not contain forbidden characters (<>:"/\\|?*) or Windows reserved words (CON, LPT[0-9], NUL, PRN, AUX).'
    ),
)


def validate_filename(filename: str) -> None:
    """
    Check if the filename is valid.
    """
    if not len(filename):
        raise ValidationError("Filename must not be empty!")

    if len(filename) != len(filename.strip()):
        raise ValidationError("Filename must not be wrapped between whitespaces!")

    if len(filename) > settings.STORAGE_FILENAME_MAX_CHAR_LENGTH:
        raise ValidationError(
            f"Filename too long, should not be longer than {settings.STORAGE_FILENAME_MAX_CHAR_LENGTH} but got {len(filename)}!"
        )

    path = Path(filename)

    for part in path.parts:
        # The validator will throw a `ValidationError` if it is not happy
        filename_validator(part)


def is_valid_filename(filename: str) -> bool:
    """Whether the provided filename is valid.

    Args:
        filename: the filename to be checked

    Returns:
        the filename is valid
    """
    try:
        validate_filename(filename)
        return True
    except Exception:
        return False


def is_qgis_project_file(filename: str) -> bool:
    """Whether the filename seems to be a QGIS project file by checking the file extension."""
    path = PurePath(filename)

    if path.suffix.lower() in (".qgs", ".qgz"):
        return True

    return False


def is_admin_restricted_file(filename: str, projectfile_filename: str | None) -> bool:
    """Whether the file has modifications restricted only to users with elevated permissions.

    Such files are the QGIS project file, QField extensions and QGIS sidecar filed (e.g. `_attachments.zip`).

    NOTE If no `projectfile_filename` is passed, then the function always returns `False`.

    Args:
        filename: the filename being checked
        projectfile_filename: the filename of the QGIS projectfile. If not provided, the function always returns `False`.

    Returns:
        whether the file is restricted file
    """
    if not projectfile_filename:
        return False

    path = PurePath(filename)
    projectfile_path = PurePath(projectfile_filename)

    # the qgis file itself
    if is_qgis_project_file(filename):
        if projectfile_path.stem == path.stem:
            return True
        else:
            return False

    # attachments
    if f"{projectfile_path.stem}_attachments.zip" == path.name:
        return True

    # label coordinates
    if f"{projectfile_path.stem}.qgd" == path.name:
        return True

    # QField plugins
    if f"{projectfile_path.stem}.qml" == path.name:
        return True

    return False


def calc_etag(file: ContentFile, part_size: int = 8 * 1024 * 1024) -> str:
    """Calculate ETag as in Object Storage (S3) of a local file.

    ETag is a MD5. But for the multipart uploaded files, the MD5 is computed from the concatenation of the MD5s of each uploaded part.

    See the inspiration of this implementation here: https://stackoverflow.com/a/58239738/1226137

    Args:
        file: the file to calculate etag for
        part_size: the size of the Object Storage part. Most Object Storages use 8MB. Defaults to 8*1024*1024.

    Returns:
        the calculated ETag value
    """
    if file.size <= part_size:
        BLOCKSIZE = 65536
        hasher = hashlib.md5()

        buf = file.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = file.read(BLOCKSIZE)

        return hasher.hexdigest()
    else:
        # Say you uploaded a 14MB file and your part size is 5MB.
        # Calculate 3 MD5 checksums corresponding to each part, i.e. the checksum of the first 5MB, the second 5MB, and the last 4MB.
        # Then take the checksum of their concatenation.
        # Since MD5 checksums are hex representations of binary data, just make sure you take the MD5 of the decoded binary concatenation, not of the ASCII or UTF-8 encoded concatenation.
        # When that's done, add a hyphen and the number of parts to get the ETag.
        md5sums = []
        for data in iter(lambda: file.read(part_size), b""):
            md5sums.append(hashlib.md5(data).digest())

        final_md5sum = hashlib.md5(b"".join(md5sums))

        return "{}-{}".format(final_md5sum.hexdigest(), len(md5sums))


def to_uuid(value: Any) -> uuid.UUID | None:
    """Converts a given value to a UUID object, or if not possible, returns None."""
    if not value:
        return None

    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def parse_range(input_range: str, file_size: int) -> tuple[int, int | None] | None:
    """Parses a range HTTP Header string.

    Arguments:
        range: string value of a HTTP range header to parse.
        file_size: size of the file to get range for, in bytes.

    Returns:
        If compliant, a tuple with start and end (if any) bytes number.
        If not, returns `None`.
    """
    match = re.match(r"^bytes=(\d+)-(\d+)?$", input_range)

    if not match:
        return None

    range_start = int(match.group(1))

    if range_start >= file_size:
        return None

    if match.group(2):
        range_end = int(match.group(2))

        if range_end >= file_size or range_end <= range_start:
            return None

    else:
        range_end = None

    return (range_start, range_end)
