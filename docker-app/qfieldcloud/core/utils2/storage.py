import hashlib
import logging
import re

from django.core.files.base import ContentFile
from django.core.files.storage import storages

import qfieldcloud.core.models
import qfieldcloud.core.utils
from qfieldcloud.filestorage.backend import QfcS3Boto3Storage

logger = logging.getLogger(__name__)


def delete_version_permanently(version_obj: qfieldcloud.core.utils.S3ObjectVersion):
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logging.info(
        f'S3 object version deletion (permanent) with "{version_obj.key=}" and "{version_obj.id=}"'
    )

    version_obj._data.delete()


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


def purge_previous_thumbnails_versions(
    project: qfieldcloud.core.models.Project,
) -> None:
    # this method applies only to S3 storage
    if not isinstance(project.file_storage, QfcS3Boto3Storage):
        return

    bucket = storages[project.file_storage].bucket  # type: ignore
    prefix = project.thumbnail.name

    if not prefix:
        return

    thumbnail_files = list(
        qfieldcloud.core.utils.list_files_with_versions(bucket, prefix)
    )

    if len(thumbnail_files) == 0:
        logger.info(f'No thumbnail found to delete for project "{project.id}"!')
        return

    assert len(thumbnail_files) == 1

    thumbnail_file = thumbnail_files[0]

    # we only keep 1 version of the thumbnail file.
    # otherwise we hit the limit of 1000.
    keep_count = 1

    old_versions_to_purge = sorted(
        thumbnail_file.versions, key=lambda v: v.last_modified, reverse=True
    )[keep_count:]

    # Remove the N oldest
    for old_version in old_versions_to_purge:
        logger.info(
            f'Purging {old_version.key=} {old_version.id=} as old version for "{thumbnail_file.latest.name}"...'
        )

        if old_version.is_latest:
            # This is not supposed to happen, as versions were sorted above,
            # but leaving it here as a security measure in case version
            # ordering changes for some reason.
            raise Exception("Trying to delete latest version")

        if not old_version.key or not re.match(
            r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/meta/thumbnail.png$",
            old_version.key,
        ):
            raise RuntimeError(
                f"Suspicious S3 file version deletion {old_version.key=} {old_version.id=}"
            )
        # TODO: any way to batch those ? will probaby get slow on production
        delete_version_permanently(old_version)
        # TODO: audit ? take implementation from files_views.py:211


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
