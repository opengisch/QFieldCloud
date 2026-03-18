import hashlib
import logging

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _

import qfieldcloud.core.models
from qfieldcloud.core.templatetags.filters import filesizeformat10

logger = logging.getLogger(__name__)


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


def format_storage_usage(useraccount: qfieldcloud.core.models.UserAccount) -> str:
    """
    Returns a string with the storage usage in a human readable format
    """
    active_storage_total = filesizeformat10(
        useraccount.current_subscription.active_storage_total_bytes
    )
    used_storage = filesizeformat10(useraccount.storage_used_bytes)
    used_storage_perc: float = useraccount.storage_used_ratio * 100
    free_storage = filesizeformat10(useraccount.storage_free_bytes)

    return _("total: {}; used: {} ({:.2f}%); free: {}").format(
        active_storage_total,
        used_storage,
        used_storage_perc,
        free_storage,
    )
