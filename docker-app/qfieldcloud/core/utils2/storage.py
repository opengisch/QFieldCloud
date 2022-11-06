from __future__ import annotations

import logging
import os
from pathlib import PurePath
from typing import IO, List, Set

import qfieldcloud.core.models
import qfieldcloud.core.utils
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpRequest
from django.http.response import HttpResponse, HttpResponseBase
from qfieldcloud.core.utils2.audit import LogEntry, audit

logger = logging.getLogger(__name__)

QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)
WEB_HTTPS_PORT = os.environ.get("WEB_HTTPS_PORT", None)


def get_attachment_dir_prefix(project: "Project", filename: str) -> str:  # noqa: F821
    """Returns the attachment dir where the file belongs to or empty string if it does not.

    Args:
        project (Project): project to check
        filename (str): filename to check

    Returns:
        str: the attachment dir or empty string if no match found
    """
    for attachment_dir in project.attachment_dirs:
        if filename.startswith(attachment_dir):
            return attachment_dir

    return ""


def file_response(
    request: HttpRequest,
    key: str,
    presigned: bool = False,
    expires: int = 60,
    version: str = None,
    as_attachment: bool = False,
) -> HttpResponseBase:
    url = ""
    filename = PurePath(key).name
    extra_params = {}

    if version is not None:
        extra_params["VersionId"] = version

    # check if we are in NGINX proxy
    http_host = request.META.get("HTTP_HOST", "")
    https_port = http_host.split(":")[-1] if ":" in http_host else "443"

    if https_port == WEB_HTTPS_PORT and not settings.IN_TEST_SUITE:
        if presigned:
            if as_attachment:
                extra_params["ResponseContentType"] = "application/force-download"
                extra_params[
                    "ResponseContentDisposition"
                ] = f'attachment;filename="{filename}"'

            url = qfieldcloud.core.utils.get_s3_client().generate_presigned_url(
                "get_object",
                Params={
                    **extra_params,
                    "Key": key,
                    "Bucket": qfieldcloud.core.utils.get_s3_bucket().name,
                },
                ExpiresIn=expires,
                HttpMethod="GET",
            )
        else:
            url = qfieldcloud.core.utils.get_s3_object_url(key)

        # Let's NGINX handle the redirect to the storage and streaming the file contents back to the client
        response = HttpResponse()
        response["X-Accel-Redirect"] = "/storage-download/"
        response["redirect_uri"] = url

        return response
    elif settings.DEBUG or settings.IN_TEST_SUITE:
        return_file = ContentFile(b"")
        qfieldcloud.core.utils.get_s3_bucket().download_fileobj(
            key,
            return_file,
            extra_params,
        )

        return FileResponse(
            return_file.open(),
            as_attachment=as_attachment,
            filename=filename,
            content_type="text/html",
        )

    raise Exception(
        "Expected to either run behind nginx proxy, debug mode or within a test suite."
    )


def upload_user_avatar(user: "User", file: IO, mimetype: str) -> str:  # noqa: F821
    """Uploads a picture as a user avatar.

    NOTE this function does NOT modify the `UserAccount.avatar_uri` field

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
    """Removes the user's avatar file.

    NOTE this function does NOT modify the `UserAccount.avatar_uri` field

    Args:
        user (User):
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    key = user.useraccount.avatar_uri
    bucket.object_versions.filter(Prefix=key).delete()


def upload_project_thumbail(
    project: "Project", file: IO, mimetype: str, filename: str  # noqa: F821
) -> str:
    """Uploads a picture as a project thumbnail.

    NOTE this function does NOT modify the `Project.thumbnail_uri` field

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

    NOTE this function does NOT modify the `Project.thumbnail_uri` field

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

    # Number of versions to keep is determined by the account type
    keep_count = (
        project.owner.useraccount.active_subscription.plan.storage_keep_versions
    )

    logger.debug(f"Keeping {keep_count} versions")

    # Process file by file
    for file in qfieldcloud.core.utils.get_project_files_with_versions(project.pk):

        # Skip the newest N
        old_versions_to_purge = sorted(
            file.versions, key=lambda v: v.last_modified, reverse=True
        )[keep_count:]

        # Debug print
        logger.debug(
            f'Purging {len(old_versions_to_purge)} out of {len(file.versions)} old versions for "{file.latest.name}"...'
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

    # Update the project size
    project.save(recompute_storage=True)


def upload_file(file: IO, key: str):
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    bucket.upload_fileobj(
        file,
        key,
    )
    return key


def upload_project_file(
    project: "Project", file: IO, filename: str  # noqa: F821
) -> str:
    key = f"projects/{project.id}/files/{filename}"
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    bucket.upload_fileobj(
        file,
        key,
    )
    return key


def delete_project_files(project_id: str) -> None:
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    prefix = f"projects/{project_id}/"
    bucket.object_versions.filter(Prefix=prefix).delete()


def delete_file(project: "Project", filename: str):  # noqa: F821
    file = qfieldcloud.core.utils.get_project_file_with_versions(project.id, filename)

    if not file:
        raise Exception("No file with such name in the given project found")

    file.delete()

    if qfieldcloud.core.utils.is_qgis_project_file(filename):
        project.project_filename = None
        project.save(recompute_storage=True)

    audit(
        project,
        LogEntry.Action.DELETE,
        changes={f"{filename} ALL": [file.latest.e_tag, None]},
    )


def delete_file_version(
    project: "Project",  # noqa: F821
    filename: str,
    version_id: str,
    include_older: bool = False,
) -> List[qfieldcloud.core.utils.S3ObjectVersion]:
    """Deletes a specific version of given file.

    Args:
        project (Project): project the file belongs to
        filename (str): filename the version belongs to
        version_id (str): version id to delete
        include_older (bool, optional): when True, versions older than the passed `version` will also be deleted. If the version_id is the latest version of a file, this parameter will treated as False. Defaults to False.

    Returns:
        int: the number of versions deleted
    """
    file = qfieldcloud.core.utils.get_project_file_with_versions(project.id, filename)

    if not file:
        raise Exception("No file with such name in the given project found")

    is_deleting_all_versions = False
    if file.latest.id == version_id:
        include_older = False

        if len(file.versions) == 1:
            is_deleting_all_versions = True

    versions_to_delete: List[qfieldcloud.core.utils.S3ObjectVersion] = []

    for file_version in file.versions:
        if file_version.id == version_id:
            versions_to_delete.append(file_version)

            if include_older:
                continue
            else:
                break

        if versions_to_delete:
            assert (
                include_older
            ), "We should continue to loop only if `include_older` is True"
            assert (
                versions_to_delete[-1].last_modified > file_version.last_modified
            ), "Assert the other versions are really older than the requested one"

            versions_to_delete.append(file_version)

    for file_version in versions_to_delete:
        file_version._data.delete()

        audit_suffix = "ALL" if is_deleting_all_versions else file_version.display

        audit(
            project,
            LogEntry.Action.DELETE,
            changes={f"{filename} {audit_suffix}": [file_version.e_tag, None]},
        )

    if is_deleting_all_versions and qfieldcloud.core.utils.is_qgis_project_file(
        filename
    ):
        project.project_filename = None
        project.save(recompute_storage=True)

    return versions_to_delete


def get_stored_package_ids(project_id: str) -> Set[str]:
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    prefix = f"projects/{project_id}/packages/"
    root_path = PurePath(prefix)
    package_ids = set()

    for file in bucket.objects.filter(Prefix=prefix):
        file_path = PurePath(file.key)
        parts = file_path.relative_to(root_path).parts
        package_ids.add(parts[0])

    return package_ids


def delete_stored_package(project_id: str, package_id: str) -> None:
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    prefix = f"projects/{project_id}/packages/{package_id}/"

    bucket.object_versions.filter(Prefix=prefix).delete()
