from __future__ import annotations

from typing import IO

import qfieldcloud.core.utils


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
