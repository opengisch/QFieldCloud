import logging

from pathlib import PurePath
from uuid import UUID

from django.shortcuts import get_object_or_404
from qfieldcloud.core.models import (
    Job,
    ProcessProjectfileJob,
    Project,
)
from qfieldcloud.filestorage.models import (
    File,
    FileVersion,
)
from qfieldcloud.core.exceptions import (
    RestrictedProjectModificationError,
    MultipleProjectsError,
    ValidationError,
)
from qfieldcloud.core import permissions_utils
from django.db import transaction
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File as DjangoFile
from django.utils.translation import gettext as _
from django.http import FileResponse, HttpResponse
from django.http.response import HttpResponseBase
from django.utils import timezone

from rest_framework.exceptions import NotFound
from rest_framework.request import Request


from qfieldcloud.core import exceptions
from qfieldcloud.core.utils2.storage import (
    get_attachment_dir_prefix,
)

from .utils import is_admin_restricted_file, is_qgis_project_file, validate_filename
from .helpers import purge_old_file_versions

logger = logging.getLogger(__name__)


def upload_project_file_version(
    request: Request,
    project_id: UUID,
    filename: str,
    file: DjangoFile,
    file_type: File.FileType,
    package_job_id: UUID | None = None,
) -> FileVersion:
    project = get_object_or_404(Project, id=project_id)

    if not filename or not filename.strip():
        logger.error(f"Filename should not be empty: {filename=}!")

        raise ValidationError(_("Filename should not be empty!"))

    try:
        validate_filename(filename)
    except DjangoValidationError as err:
        logger.error(f"Invalid {filename=}: {err}!")

        raise err

    # check if the project restricts file modification to admins only
    if (
        file_type == File.FileType.PROJECT_FILE
        and (
            is_admin_restricted_file(filename, project.project_filename)
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
        and project.project_filename is not None
        and PurePath(filename) != PurePath(project.project_filename)
    ):
        logger.error(f"Only one QGIS project per project allowed for {filename=}!")

        raise MultipleProjectsError("Only one QGIS project per project allowed")

    # check if the user has enough storage to upload the file
    permissions_utils.check_can_upload_file(
        project,
        request.auth.client_type,  # type: ignore
        file.size,
    )

    with transaction.atomic():
        file_version = FileVersion.objects.add_version(
            project=project,
            filename=filename,
            content=file,
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
                is_qgis_file or project.project_filename is not None
            ):
                if is_qgis_file:
                    project.project_filename = filename
                    update_fields.append("project_filename")

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
    as_attachment: bool = False,
) -> HttpResponseBase:
    version_id = request.GET.get("version")

    if version_id:
        file_version = FileVersion.objects.get(
            id=version_id,
            file__project_id=project_id,
            file__name=filename,
            file__file_type=file_type,
        )
    else:
        file = File.objects.get(
            project_id=project_id,
            name=filename,
            file_type=file_type,
        )

        assert file.latest_version

        file_version = file.latest_version

    # check if we are in NGINX proxy
    http_host = request.headers.get("host", "")
    https_port = http_host.split(":")[-1] if ":" in http_host else "443"

    if https_port == settings.WEB_HTTPS_PORT and not settings.IN_TEST_SUITE:
        # this is the relative path of the file, including the containing directories.
        # We cannot use `ContentFile.path` with object storage, as there is no concept for "absolute path".
        storage_filename = file_version.content.name

        url = file_version.content.storage.url(
            storage_filename,
            parameters={
                "ResponseContentType": "application/force-download",
                "ResponseContentDisposition": f'attachment;filename="{filename}"',
            },
            # keep it a low number, in seconds
            expire=600,
            http_method="GET",
        )

        # Let's NGINX handle the redirect to the storage and streaming the file contents back to the client
        response = HttpResponse()
        response["X-Accel-Redirect"] = "/storage-download/"
        response["redirect_uri"] = url

        return response
    elif settings.DEBUG or settings.IN_TEST_SUITE:
        return FileResponse(
            file_version.content.open(),
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
    """_summary_

    Args:
        request (Request): _description_
        filename (str): _description_


    Raises:
        Exception: Raised when the passed `version_id` will delete the only `FileVersion` remaining for that file.
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
            project.project_filename = None
            update_fields.append("project_filename")

        project.file_storage_bytes -= bytes_to_delete

        project.save(update_fields=update_fields)
