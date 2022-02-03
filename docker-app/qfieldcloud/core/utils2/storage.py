from __future__ import annotations

import logging
from typing import IO

import qfieldcloud.core.utils
from qfieldcloud.core.models import UserAccount

logger = logging.getLogger(__name__)


def upload_user_avatar(user: "User", file: IO, mimetype: str) -> str:  # noqa: F821
    """Uploads a picture as a user avatar.

    NOTE you need to set the URI to the user account manually

    Args:
        user (User):
        file (IO): file used as avatar
        mimetype (str): file mimetype

    Returns:
        str: URI to the avatar
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()

    if mimetype == "image/svg+xml":
        extension = "svg"
    elif mimetype == "image/png":
        extension = "png"
    elif mimetype == "image/jpeg":
        extension = "jpg"
    else:
        raise Exception(f"Unknown mimetype: {mimetype}")

    key = f"users/{user.username}/avatar.{extension}"
    bucket.upload_fileobj(
        file,
        key,
        {
            "ACL": "public-read",
            "ContentType": mimetype,
        },
    )
    return key


def remove_user_avatar(user: "User") -> None:  # noqa: F821
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    key = user.useraccount.avatar_uri
    bucket.object_versions.filter(Prefix=key).delete()


def upload_project_thumbail(
    project: "Project", file: IO, mimetype: str, filename: str  # noqa: F821
) -> str:
    """Uploads a picture as a project thumbnail.

    NOTE you need to set the URI to the project manually

    Args:
        project (Project):
        file (IO): file used as thumbail
        mimetype (str): file mimetype
        filename (str): filename

    Returns:
        str: URI to the thumbnail
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()

    # for now we always expect PNGs
    if mimetype == "image/svg+xml":
        extension = "svg"
    elif mimetype == "image/png":
        extension = "png"
    elif mimetype == "image/jpeg":
        extension = "jpg"
    else:
        raise Exception(f"Unknown mimetype: {mimetype}")

    key = f"projects/{project.id}/meta/{filename}.{extension}"
    bucket.upload_fileobj(
        file,
        key,
        {
            # TODO most probably this is not public-read, since the project might be private
            "ACL": "public-read",
            "ContentType": mimetype,
        },
    )
    return key


def remove_project_thumbail(project: "Project") -> None:  # noqa: F821
    """Uploads a picture as a project thumbnail.

    NOTE you need to remove the URI to the project manually
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    key = project.thumbnail_uri
    bucket.object_versions.filter(Prefix=key).delete()


def purge_old_file_versions(project: "Project") -> None:  # noqa: F821
    """
    Deletes old versions of all files in the given project. Will keep __3__
    versions for COMMUNITY user accounts, and __10__ versions for PRO user
    accounts
    """

    logger.info(f"Cleaning up old files for {project}")

    # Determine account type
    account_type = project.owner.useraccount.account_type
    if account_type == UserAccount.TYPE_COMMUNITY:
        keep_count = 3
    elif account_type == UserAccount.TYPE_PRO:
        keep_count = 10
    else:
        raise NotImplementedError(f"Unknown account type {account_type}")

    logger.debug(f"Keeping {keep_count} versions")

    # Process file by file
    for file in qfieldcloud.core.utils.get_project_files_with_versions(project.pk):

        filename = file.latest.name
        old_versions = file.versions

        # Sort by date (newest first)
        old_versions.sort(key=lambda i: i.last_modified, reverse=True)

        # Skip the newest N
        old_versions_to_purge = old_versions[keep_count:]

        # Debug print
        all_count = len(old_versions)
        topurge_count = len(old_versions_to_purge)
        logger.debug(
            f'Purging {topurge_count} out of {all_count} old versions for "{filename}"...'
        )

        # Remove the N oldest
        for old_version in old_versions_to_purge:
            if old_version.is_latest:
                # This is not supposed to happen, as versions were sorted above,
                # but leaving it here as a security measure in case version
                # ordering changes for some reason.
                raise Exception("Trying to delete latest version")
            # TODO: any way to batch those ? will probaby get slow on production
            old_version._data.delete()
            # TODO: audit ? take implementation from files_views.py:211
