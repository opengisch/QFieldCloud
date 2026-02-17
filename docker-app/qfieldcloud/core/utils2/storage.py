import hashlib

from django.core.files.base import ContentFile

import qfieldcloud.core.models


def get_attachment_dir_prefix(
    project: qfieldcloud.core.models.Project, filename: str
) -> str:  # noqa: F821
    """Returns the attachment dir where the file belongs to or empty string if it does not.

    Args:
        project: project to check
        filename: filename to check

    Returns:
        the attachment dir or empty string if no match found
    """
    for attachment_dir in project.attachment_dirs:
        if filename.startswith(attachment_dir):
            return attachment_dir

    return ""


def calculate_checksums(
    content: ContentFile, alrgorithms: tuple[str, ...], blocksize: int = 65536
) -> tuple[bytes, ...]:
    """Calculates checksums on given file for given algorithms."""
    hashers = []
    for alrgorithm in alrgorithms:
        hashers.append(getattr(hashlib, alrgorithm)())

    for chunk in content.chunks(blocksize):
        for hasher in hashers:
            hasher.update(chunk)

    content.seek(0)

    checksums = []
    for hasher in hashers:
        checksums.append(hasher.digest())

    return tuple(checksums)
