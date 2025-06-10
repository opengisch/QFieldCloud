"""A module with legacy file storage management.

Todo:
    * Delete with QF-4963 Drop support for legacy storage
"""

from __future__ import annotations

import hashlib
import logging
import re
from enum import Enum
from pathlib import PurePath
from typing import IO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.http import FileResponse, HttpRequest
from django.http.response import HttpResponse, HttpResponseBase
from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

import qfieldcloud.core.models
import qfieldcloud.core.utils
from qfieldcloud.core.utils2.audit import LogEntry, audit
from qfieldcloud.filestorage.backend import QfcS3Boto3Storage

logger = logging.getLogger(__name__)


def legacy_only(func):
    """
    Decorator to verify that given project is stored on the legacy storage.
    Otherwise, it calls the decorated function.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
        * Delete all decorated functions with QF-4963 Drop support for legacy storage
    """

    def wrapper(project, *args, **kwargs):
        if not project.uses_legacy_storage:
            raise NotImplementedError(
                f"This function is not implemented for '{project.file_storage}' file storage!"
            )

        return func(project, *args, **kwargs)

    return wrapper


def _delete_by_prefix_versioned(prefix: str):
    """
    Delete all objects and their versions starting with a given prefix.

    Similar concept to delete a directory.
    Do not use when deleting objects with precise key, as it will delete all objects that start with the same name.
    Deleting with this method will leave a deleted version and the deletion is not permanent.
    In other words, it is a soft delete. Read more here: https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectVersions.html

    Args:
        prefix: Object's prefix to search and delete. Check the given prefix if it matches the expected format before using this function!

    Raises:
        RuntimeError: When the given prefix is not a string, empty string or leading slash. Check is very basic, do a throrogh checks before calling!

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logging.info(f"S3 object deletion (versioned) with {prefix=}")

    # Illegal prefix is either empty string ("") or slash ("/"), it will delete random 1000 objects.
    if not isinstance(prefix, str) or prefix == "" or prefix == "/":
        raise RuntimeError(f"Attempt to delete S3 object with illegal {prefix=}")

    bucket = qfieldcloud.core.utils.get_s3_bucket()
    return bucket.objects.filter(Prefix=prefix).delete()


def _delete_by_prefix_permanently(prefix: str):
    """
    Delete all objects and their versions starting with a given prefix.

    Similar concept to delete a directory.
    Do not use when deleting objects with precise key, as it will delete all objects that start with the same name.
    Deleting with this method will permanently delete objects and all their versions and the deletion is impossible to recover.
    In other words, it is a hard delete. Read more here: https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectVersions.html

    Args:
        prefix: Object's prefix to search and delete. Check the given prefix if it matches the expected format before using this function!

    Raises:
        RuntimeError: When the given prefix is not a string, empty string or leading slash. Check is very basic, do a throrogh checks before calling!

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logging.info(f"S3 object deletion (permanent) with {prefix=}")

    # Illegal prefix is either empty string ("") or slash ("/"), it will delete random 1000 object versions.
    if not isinstance(prefix, str) or prefix == "" or prefix == "/":
        raise RuntimeError(f"Attempt to delete S3 object with illegal {prefix=}")

    bucket = qfieldcloud.core.utils.get_s3_bucket()
    return bucket.object_versions.filter(Prefix=prefix).delete()


def _delete_by_key_versioned(key: str):
    """
    Delete an object with a given key.

    Deleting with this method will leave a deleted version and the deletion is not permanent.
    In other words, it is a soft delete.

    Args:
        key: Object's key to search and delete. Check the given key if it matches the expected format before using this function!

    Raises:
        RuntimeError: When the given key is not a string, empty string or leading slash. Check is very basic, do a throrogh checks before calling!

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logging.info(f"Delete (versioned) S3 object with {key=}")

    # prevent disastrous results when prefix is either empty string ("") or slash ("/").
    if not isinstance(key, str) or key == "" or key == "/":
        raise RuntimeError(
            f"Attempt to delete (versioned) S3 object with illegal {key=}"
        )

    bucket = qfieldcloud.core.utils.get_s3_bucket()

    return bucket.delete_objects(
        Delete={
            "Objects": [
                {
                    "Key": key,
                }
            ],
        },
    )


def _delete_by_key_permanently(key: str):
    """
    Delete an object with a given key.

    Deleting with this method will permanently delete objects and all their versions and the deletion is impossible to recover.
    In other words, it is a hard delete.

    Args:
        key: Object's key to search and delete. Check the given key if it matches the expected format before using this function!

    Raises:
        RuntimeError: When the given key is not a string, empty string or leading slash. Check is very basic, do a throrogh checks before calling!

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logging.info(f"Delete (permanently) S3 object with {key=}")

    # prevent disastrous results when prefix is either empty string ("") or slash ("/").
    if not isinstance(key, str) or key == "" or key == "/":
        raise RuntimeError(
            f"Attempt to delete (permanently) S3 object with illegal {key=}"
        )

    bucket = qfieldcloud.core.utils.get_s3_bucket()

    # NOTE filer by prefix will return all objects with that prefix. E.g. for given key="orho.tif", it will return "ortho.tif", "ortho.tif.aux.xml" and "ortho.tif.backup"
    temp_objects = bucket.object_versions.filter(
        Prefix=key,
    )
    object_to_delete: list[ObjectIdentifierTypeDef] = []
    for temp_object in temp_objects:
        # filter out objects that do not have the same key as the requested deletion key.
        if temp_object.key != key:
            continue

        object_to_delete.append(
            {
                "Key": key,
                "VersionId": temp_object.id,
            }
        )

    if len(object_to_delete) == 0:
        logging.warning(
            f"Attempt to delete (permanently) S3 objects did not match any existing objects for {key=}",
            extra={
                "all_objects": [
                    (o.key, o.version_id, o.e_tag, o.last_modified, o.is_latest)
                    for o in temp_objects
                ]
            },
        )
        return None

    logging.info(
        f"Delete (permanently) S3 object with {key=} will delete delete {len(object_to_delete)} version(s)"
    )

    return bucket.delete_objects(
        Delete={
            "Objects": object_to_delete,
        },
    )


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


def file_response(
    request: HttpRequest,
    key: str,
    expires: int = 60,
    version: str | None = None,
    as_attachment: bool = False,
) -> HttpResponseBase:
    """Return a Django HTTP response with nginx speedup if reverse proxy detected.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    url = ""
    filename = PurePath(key).name
    extra_params = {}

    if version is not None:
        extra_params["VersionId"] = version

    # check if we are in NGINX proxy
    http_host = request.headers.get("host", "")
    https_port = http_host.split(":")[-1] if ":" in http_host else "443"

    if https_port == settings.WEB_HTTPS_PORT and not settings.IN_TEST_SUITE:
        if as_attachment:
            extra_params["ResponseContentType"] = "application/force-download"
            extra_params["ResponseContentDisposition"] = (
                f'attachment;filename="{filename}"'
            )

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


class ImageMimeTypes(str, Enum):
    svg = "image/svg+xml"
    png = "image/png"
    jpg = "image/jpeg"

    @classmethod
    def or_none(cls, string: str) -> ImageMimeTypes | None:
        try:
            return cls(string)
        except ValueError:
            return None


def upload_user_avatar(
    user: qfieldcloud.core.models.User, file: IO, mimetype: ImageMimeTypes
) -> str:  # noqa: F821
    """Uploads a picture as a user avatar.

    NOTE this function does NOT modify the `UserAccount.legacy_avatar_uri` field

    Args:
        user:
        file: file used as avatar
        mimetype: file mimetype

    Returns:
        URI to the avatar

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    key = f"users/{user.username}/avatar.{mimetype.name}"
    bucket.upload_fileobj(
        file,
        key,
        {
            "ContentType": mimetype.value,
        },
    )
    return key


def delete_user_avatar(user: qfieldcloud.core.models.User) -> None:  # noqa: F821
    """Deletes the user's avatar file.

    NOTE this function does NOT modify the `UserAccount.legacy_avatar_uri` field

    Args:
        user:

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    key = user.useraccount.legacy_avatar_uri

    # it well could be the user has no avatar yet
    if not key:
        return

    # e.g. "users/suricactus/avatar.svg"
    if not key or not re.match(r"^users/[\w-]+/avatar\.(png|jpg|svg)$", key):
        raise RuntimeError(f"Suspicious S3 deletion of user avatar {key=}")

    _delete_by_key_permanently(key)


@legacy_only
def upload_project_thumbail(
    project: qfieldcloud.core.models.Project,
    file: IO,
    mimetype: str,
    filename: str,  # noqa: F821
) -> str:
    """Uploads a picture as a project thumbnail.

    NOTE this function does NOT modify the `Project.thumbnail_uri` field

    Args:
        project:
        file: file used as thumbail
        mimetype: file mimetype
        filename: filename

    Returns:
        URI to the thumbnail

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
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
            "ContentType": mimetype,
        },
    )
    return key


@legacy_only
def delete_project_thumbnail(
    project: qfieldcloud.core.models.Project,
) -> None:  # noqa: F821
    """Delete a picture as a project thumbnail.

    NOTE this function does NOT modify the `Project.thumbnail_uri` field

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    key = project.legacy_thumbnail_uri

    # it well could be the project has no thumbnail yet
    if not key:
        return

    if not key or not re.match(
        # e.g. "projects/9bf34e75-0a5d-47c3-a2f0-ebb7126eeccc/meta/thumbnail.png"
        r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/meta/thumbnail\.(png|jpg|svg)$",
        key,
    ):
        raise RuntimeError(f"Suspicious S3 deletion of project thumbnail image {key=}")

    _delete_by_key_permanently(key)


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


@legacy_only
def purge_old_file_versions_legacy(
    project: qfieldcloud.core.models.Project,
) -> None:  # noqa: F821
    """
    Deletes old versions of all files in the given project. Will keep __3__
    versions for COMMUNITY user accounts, and __10__ versions for PRO user
    accounts

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """

    keep_count = project.owner_aware_storage_keep_versions

    logger.info(f"Cleaning up old files for {project} to {keep_count} versions")

    # Process file by file
    for file in qfieldcloud.core.utils.get_project_files_with_versions(project.pk):
        # Skip the newest N
        old_versions_to_purge = sorted(
            file.versions, key=lambda v: v.last_modified, reverse=True
        )[keep_count:]

        # Debug print
        logger.info(
            f'Purging {len(old_versions_to_purge)} out of {len(file.versions)} old versions for "{file.latest.name}"...'
        )

        # Remove the N oldest
        for old_version in old_versions_to_purge:
            logger.info(
                f'Purging {old_version.key=} {old_version.id=} as old version for "{file.latest.name}"...'
            )

            if old_version.is_latest:
                # This is not supposed to happen, as versions were sorted above,
                # but leaving it here as a security measure in case version
                # ordering changes for some reason.
                raise Exception("Trying to delete latest version")

            if not old_version.key or not re.match(
                r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/.+$", old_version.key
            ):
                raise RuntimeError(
                    f"Suspicious S3 file version deletion {old_version.key=} {old_version.id=}"
                )
            # TODO: any way to batch those ? will probaby get slow on production
            delete_version_permanently(old_version)
            # TODO: audit ? take implementation from files_views.py:211

    # Update the project size
    project.save(recompute_storage=True)


def upload_file(file: IO, key: str):
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    bucket.upload_fileobj(
        file,
        key,
    )
    return key


@legacy_only
def upload_project_file(
    project: qfieldcloud.core.models.Project, file: IO, filename: str
) -> str:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    key = f"projects/{project.id}/files/{filename}"
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    bucket.upload_fileobj(
        file,
        key,
    )
    return key


def delete_all_project_files_permanently(project_id: str) -> None:
    """Deletes all project files permanently.

    Args:
        project_id: the project which files shall be deleted. Note that the `project_id` might be a of a already deleted project which files are still dangling around.

    Raises:
        RuntimeError: if the produced Object Storage key to delete is not in the right format

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    prefix = f"projects/{project_id}/"

    if not re.match(r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/$", prefix):
        raise RuntimeError(
            f"Suspicious S3 deletion of all project files with {prefix=}"
        )

    _delete_by_prefix_permanently(prefix)


@legacy_only
def delete_project_file_permanently(
    project: qfieldcloud.core.models.Project, filename: str
):  # noqa: F821
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    logger.info(f"Requested delete (permanent) of project file {filename=}")

    file = qfieldcloud.core.utils.get_project_file_with_versions(
        str(project.id), filename
    )

    if not file:
        raise Exception(
            f"No file with such name in the given project found {filename=}"
        )

    if not re.match(r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/.+$", file.latest.key):
        raise RuntimeError(f"Suspicious S3 file deletion {file.latest.key=}")

    # NOTE the file operations depend on HTTP calls to the S3 storage and they might fail,
    # we need to choose source of truth between DB and S3.
    # For now the source of truth is what is on the S3 storage,
    # because we do most of our file operations directly by calling the S3 API.
    # 1. S3 storage modification. If it fails, it will cancel the transaction
    # and do not update anything in the database.
    # We assume S3 storage is transactional, while it might not be true.
    # 2. DB modification. If it fails, the states betewen DB and S3 mismatch,
    # but can be easyly synced from the S3 to DB with a manual script.
    with transaction.atomic():
        _delete_by_key_permanently(file.latest.key)

        update_fields = ["file_storage_bytes"]

        if qfieldcloud.core.utils.is_the_qgis_file(filename):
            update_fields.append("the_qgis_file_name")
            project.the_qgis_file_name = None

        file_storage_bytes = project.file_storage_bytes - sum(
            [v.size for v in file.versions]
        )
        project.file_storage_bytes = max(file_storage_bytes, 0)

        project.save(update_fields=update_fields)

        # NOTE force audits to be required when deleting files
        audit(
            project,
            LogEntry.Action.DELETE,
            changes={f"{filename} ALL": [file.latest.e_tag, None]},
        )


@legacy_only
def delete_project_file_version_permanently(
    project: qfieldcloud.core.models.Project,
    filename: str,
    version_id: str,
    include_older: bool = False,
) -> list[qfieldcloud.core.utils.S3ObjectVersion]:
    """Deletes a specific version of given file.

    Args:
        project: project the file belongs to
        filename: filename the version belongs to
        version_id: version id to delete
        include_older: when True, versions older than the passed `version` will also be deleted. If the version_id is the latest version of a file, this parameter will treated as False. Defaults to False.

    Returns:
        the number of versions deleted

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    project_id = str(project.id)
    file = qfieldcloud.core.utils.get_project_file_with_versions(project_id, filename)

    if not file:
        raise Exception(
            f"No file with such name in the given project found {filename=} {version_id=}"
        )

    if file.latest.id == version_id:
        include_older = False

        if len(file.versions) == 1:
            raise RuntimeError(
                "Forbidded attempt to delete a specific file version which is the only file version available."
            )

    versions_latest_first = list(reversed(file.versions))
    versions_to_delete: list[qfieldcloud.core.utils.S3ObjectVersion] = []

    for file_version in versions_latest_first:
        if file_version.id == version_id:
            versions_to_delete.append(file_version)

            if include_older:
                continue
            else:
                break

        if versions_to_delete:
            assert include_older, (
                "We should continue to loop only if `include_older` is True"
            )
            assert versions_to_delete[-1].last_modified > file_version.last_modified, (
                "Assert the other versions are really older than the requested one"
            )

            versions_to_delete.append(file_version)

    with transaction.atomic():
        for file_version in versions_to_delete:
            if (
                not re.match(
                    r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/.+$",
                    file_version._data.key,
                )
                or not file_version.id
            ):
                raise RuntimeError(
                    f"Suspicious S3 file version deletion {filename=} {version_id=} {include_older=}"
                )

            audit_suffix = file_version.display

            audit(
                project,
                LogEntry.Action.DELETE,
                changes={f"{filename} {audit_suffix}": [file_version.e_tag, None]},
            )

            delete_version_permanently(file_version)

    project.save(recompute_storage=True)

    return versions_to_delete


@legacy_only
def get_stored_package_ids(project: qfieldcloud.core.models.Project) -> set[str]:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    project_id = project.id
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    prefix = f"projects/{project_id}/packages/"
    root_path = PurePath(prefix)
    package_ids = set()

    for file in bucket.objects.filter(Prefix=prefix):
        file_path = PurePath(file.key)
        parts = file_path.relative_to(root_path).parts
        package_ids.add(parts[0])

    return package_ids


@legacy_only
def delete_stored_package(
    project: qfieldcloud.core.models.Project, package_id: str
) -> None:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    project_id = str(project.id)
    prefix = f"projects/{project_id}/packages/{package_id}/"

    if not re.match(
        # e.g. "projects/878039c4-b945-4356-a44e-a908fd3f2263/packages/633cd4f7-db14-4e6e-9b2b-c0ce98f9d338/"
        r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/packages/[\w]{8}(-[\w]{4}){3}-[\w]{12}/$",
        prefix,
    ):
        raise RuntimeError(
            f"Suspicious S3 deletion on stored project package {project_id=} {package_id=}"
        )

    _delete_by_prefix_permanently(prefix)


@legacy_only
def get_project_file_storage_in_bytes(project: qfieldcloud.core.models.Project) -> int:
    """Calculates the project files storage in bytes, including their versions.

    WARNING This function can be quite slow on projects with thousands of files.

    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    project_id = str(project.id)
    bucket = qfieldcloud.core.utils.get_s3_bucket()
    total_bytes = 0
    prefix = f"projects/{project_id}/files/"

    logger.info(f"Project file storage size requested for {project_id=}")

    if not re.match(r"^projects/[\w]{8}(-[\w]{4}){3}-[\w]{12}/files/$", prefix):
        raise RuntimeError(
            f"Suspicious S3 calculation of all project files with {prefix=}"
        )

    for version in bucket.object_versions.filter(Prefix=prefix):
        total_bytes += version.size or 0

    return total_bytes


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
