import logging
from datetime import datetime
from datetime import timezone as tz
from pathlib import PurePath
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.http import FileResponse, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import parse_http_date_safe
from rest_framework.exceptions import NotFound
from rest_framework.request import Request

from qfieldcloud.core import exceptions, permissions_utils
from qfieldcloud.core.exceptions import (
    InvalidRangeError,
    MultipleProjectsError,
    RestrictedProjectModificationError,
)
from qfieldcloud.core.models import (
    Job,
    ProcessProjectfileJob,
    Project,
)
from qfieldcloud.core.utils2.storage import (
    get_attachment_dir_prefix,
)
from qfieldcloud.filestorage.models import (
    File,
    FileVersion,
)
from qfieldcloud.filestorage.utils import (
    is_admin_restricted_file,
    is_qgis_project_file,
    parse_range,
    validate_filename,
)

from .helpers import purge_old_file_versions

logger = logging.getLogger(__name__)


def upload_project_file_version(
    request: Request,
    project_id: UUID,
    filename: str,
    file_type: File.FileType,
    package_job_id: UUID | None = None,
) -> FileVersion:
    # Only one file allowed to be uploaded at once
    if len(request.FILES.getlist("file")) > 1:
        raise exceptions.MultipleContentsError()

    uploaded_file = request.FILES.get("file")

    if not uploaded_file:
        raise exceptions.EmptyContentError(
            f'Missing file contents for "{filename}" from the request!'
        )

    project = get_object_or_404(Project, id=project_id)

    try:
        validate_filename(filename)
    except DjangoValidationError as err:
        logger.error(f"Invalid {filename=}: {err}!")

        raise err

    # check if the project restricts file modification to admins only
    if (
        file_type == File.FileType.PROJECT_FILE
        and (
            is_admin_restricted_file(filename, project.the_qgis_file_name)
            or is_qgis_project_file(filename)
        )
    ) and not permissions_utils.can_modify_qgis_projectfile(request.user, project):
        logger.error(
            f"The project restricts modification of the QGIS project file to managers and administrators for {filename=}!"
        )

        raise RestrictedProjectModificationError(
            "The project restricts modification of the QGIS project file to managers and administrators."
        )

    is_qgis_file = is_qgis_project_file(filename)

    # check only one qgs/qgz file per project for project files
    if (
        file_type == File.FileType.PROJECT_FILE
        and is_qgis_file
        and project.the_qgis_file_name is not None
        and PurePath(filename) != PurePath(project.the_qgis_file_name)
    ):
        logger.info(f"Only one QGIS project per project allowed for {filename=}!")

        raise MultipleProjectsError("Only one QGIS project per project allowed")

    # check if the user has enough storage to upload the file
    if hasattr(request, "auth") and hasattr(request.auth, "client_type"):
        client_type = request.auth.client_type
    else:
        client_type = request.session.get("client_type")

    permissions_utils.check_can_upload_file(
        project,
        client_type,
        uploaded_file.size,
    )

    with transaction.atomic():
        file_version = FileVersion.objects.add_version(
            project=project,
            filename=filename,
            content=uploaded_file,
            file_type=file_type,
            uploaded_by=request.user,
            package_job_id=package_job_id,
        )

        if file_type == File.FileType.PROJECT_FILE:
            # Select for update the project so we can update it, especially the `file_storage_bytes` bit.
            # It guarantees there will be no other file upload editing the same project row.
            project = Project.objects.select_for_update().get(id=project.id)
            update_fields = ["data_last_updated_at", "file_storage_bytes"]

            if get_attachment_dir_prefix(project, filename) == "" and (
                is_qgis_file or project.the_qgis_file_name is not None
            ):
                if is_qgis_file:
                    project.the_qgis_file_name = filename
                    update_fields.append("the_qgis_file_name")

                running_jobs = ProcessProjectfileJob.objects.filter(
                    project=project,
                    created_by=request.user,
                    status__in=[
                        Job.Status.PENDING,
                        Job.Status.QUEUED,
                        Job.Status.STARTED,
                    ],
                )

                if not running_jobs.exists():
                    ProcessProjectfileJob.objects.create(
                        project=project, created_by=request.user
                    )

            project.data_last_updated_at = timezone.now()
            project.file_storage_bytes += file_version.size
            project.save(update_fields=update_fields)
        elif file_type == File.FileType.PACKAGE_FILE:
            # nothing to do when we upload a package file
            pass
        else:
            raise NotImplementedError(f"Unknown FileType: {file_type=}")

    if file_type == File.FileType.PROJECT_FILE:
        purge_old_file_versions(project)
    else:
        # do nothing, only `file_type=PROJECT_FILE` files are versioned, the rest are not versioned
        pass

    return file_version


def download_project_file_version(
    request: Request,
    project_id: UUID,
    filename: str,
    file_type: File.FileType,
    as_attachment: bool = True,
    package_job_id: UUID | None = None,
) -> HttpResponseBase:
    version_id = request.GET.get("version")

    if file_type == File.FileType.PACKAGE_FILE and not package_job_id:
        raise Exception(
            f"When downloading a package file the `package_job_id` should be non-empty, but got {package_job_id=}."
        )

    if version_id:
        filters = Q(
            id=version_id,
            file__project_id=project_id,
            file__name=filename,
            file__file_type=file_type,
        )

        if package_job_id:
            filters &= Q(
                Q(file__package_job_id=package_job_id)
                | Q(file__file_type=File.FileType.PROJECT_FILE)
            )

        file_version = FileVersion.objects.get(filters)
    else:
        filters = Q(
            project_id=project_id,
            name=filename,
            file_type=file_type,
        )

        if package_job_id:
            filters &= Q(
                Q(package_job_id=package_job_id)
                | Q(file_type=File.FileType.PROJECT_FILE)
            )

        file = File.objects.select_related("latest_version").get(filters)

        assert file.latest_version

        file_version = file.latest_version

    return download_field_file(
        request,
        file_version.content,
        filename,
        as_attachment,
    )


def download_field_file(
    request: Request,
    field_file: FieldFile,
    filename: str | None = None,
    as_attachment: bool = False,
) -> HttpResponseBase:
    if not filename:
        filename = field_file.name

    # While we should always have a filename, either as a parameter, or obtained from the uploaded file itself,
    # we can be paranoid and check if there is a one.
    # This scenario is more to prevent developers from mistakes, rather than real world situation.
    if not filename:
        raise Exception("Missing filename in `download_field_file`!")

    # check if we are in NGINX proxy
    http_host = request.headers.get("host", "")
    https_port = http_host.split(":")[-1] if ":" in http_host else "443"

    download_range = request.headers.get("Range", "")
    if download_range:
        file_size = field_file.size
        range_match = parse_range(download_range, file_size)

        if not range_match:
            raise InvalidRangeError("The provided HTTP range header is invalid.")

        range_start, range_end = range_match

        if range_end is None:
            range_end = file_size - 1

        range_length = range_end - range_start + 1

        if range_length < settings.QFIELDCLOUD_MINIMUM_RANGE_HEADER_LENGTH:
            raise InvalidRangeError(
                "Requested range too small, expected at least {} but got {} bytes".format(
                    settings.QFIELDCLOUD_MINIMUM_RANGE_HEADER_LENGTH, range_length
                )
            )

    if https_port == settings.WEB_HTTPS_PORT and not settings.IN_TEST_SUITE:
        # this is the relative path of the file, including the containing directories.
        # We cannot use `ContentFile.path` with object storage, as there is no concept for "absolute path".
        storage_filename = field_file.name
        parameters: dict[str, str | datetime] = {}

        if_match_etags = request.headers.get("if-match", "")
        if_none_match_etags = request.headers.get("if-none-match", "")
        if_modified_since_int = parse_http_date_safe(
            request.headers.get("if-modified-since", "")
        )
        if_unmodified_since_int = parse_http_date_safe(
            request.headers.get("if-unmodified-since", "")
        )

        if if_match_etags:
            parameters["IfMatch"] = if_match_etags

        if if_none_match_etags:
            parameters["IfNoneMatch"] = if_none_match_etags

        if if_modified_since_int:
            parameters["IfModifiedSince"] = datetime.fromtimestamp(
                if_modified_since_int, tz=tz.utc
            )

        if if_unmodified_since_int:
            parameters["IfUnmodifiedSince"] = datetime.fromtimestamp(
                if_unmodified_since_int, tz=tz.utc
            )

        if as_attachment:
            parameters.update(
                {
                    "ResponseContentType": "application.force-download",
                    "ResponseContentDisposition": f'attachment;filename="{filename}"',
                }
            )

        url = field_file.storage.url(
            storage_filename,
            parameters=parameters,  # type: ignore
            # keep it a low number, in seconds
            expire=600,  # type: ignore
            http_method="GET",  # type: ignore
        )

        # Let's NGINX handle the redirect to the storage and streaming the file contents back to the client
        response = HttpResponse()
        response["X-Accel-Redirect"] = "/storage-download/"
        response["redirect_uri"] = url

        if download_range:
            response["file_range"] = download_range

        field_file.storage.patch_nginx_download_redirect(response)  # type: ignore

        return response
    elif settings.DEBUG or settings.IN_TEST_SUITE:
        if download_range:
            file = field_file.open()

            file.seek(range_start)
            content = file.read(range_length)

            response = HttpResponse(
                content, status=206, content_type="application/octet-stream"
            )

            response["Content-Range"] = f"bytes {range_start}-{range_end}/{file_size}"
            response["Content-Length"] = str(range_length)
            response["Accept-Ranges"] = "bytes"

            return response

        return FileResponse(
            field_file.open(),
            as_attachment=as_attachment,
            filename=filename,
            content_type="text/html",
        )

    raise Exception(
        "Expected to either run behind nginx proxy, debug mode or within a test suite."
    )


def delete_project_file_version(
    request: Request,
    project_id: UUID,
    filename: str,
) -> None:
    """Deletes a given project file, or if the version is passed, only specific version.

    The version can be passed either with `version` query parameter or `x-file-version` header.

    Args:
        request: The Django request
        filename: The filename to be deleted

    Raises:
        Exception: Raised when the passed `version` will delete the only `FileVersion` remaining for that file.
        NotFound: Raised when the requested file is not found.
        NotFound: Raised when the requested file version is not found.
    """
    version_id = request.GET.get("version", request.headers.get("x-file-version"))
    bytes_to_delete = 0

    try:
        if version_id:
            file_versions_qs = FileVersion.objects.filter(
                file__name=filename,
                file__project_id=project_id,
                file__file_type=File.FileType.PROJECT_FILE,
            )

            if file_versions_qs.count() <= 1:
                raise exceptions.ExplicitDeletionOfLastFileVersionError(
                    f"The requested {filename=} with {version_id=} for {project_id=} is the only file version, which prevents it from deletion!"
                )

            object_to_delete = file_versions_qs.get(id=version_id)
            bytes_to_delete = object_to_delete.size
        else:
            object_to_delete = File.objects.get(
                project_id=project_id,
                name=filename,
                file_type=File.FileType.PROJECT_FILE,
            )
            bytes_to_delete = object_to_delete.get_total_versions_size()
    except File.DoesNotExist:
        raise NotFound(
            detail=f"The requested {filename=} for {project_id=} does not exist!"
        )
    except FileVersion.DoesNotExist:
        raise NotFound(
            detail=f"The requested {version_id=} of {filename=} for {project_id=} does not exist!"
        )

    object_to_delete.delete()

    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=project_id)
        update_fields = ["file_storage_bytes"]

        if (
            is_qgis_project_file(filename)
            and not File.objects.filter(
                name=filename,
                project_id=project_id,
            ).exists()
        ):
            project.the_qgis_file_name = None
            update_fields.append("the_qgis_file_name")

        project.file_storage_bytes -= bytes_to_delete

        project.save(update_fields=update_fields)
