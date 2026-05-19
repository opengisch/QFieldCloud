import logging
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions
from qfieldcloud.core import permissions_utils as perms
from qfieldcloud.core.models import PackageJob, Project
from qfieldcloud.core.serializers import LatestPackageSerializer
from qfieldcloud.core.utils2 import storage
from qfieldcloud.filestorage.models import (
    File,
)
from qfieldcloud.filestorage.serializers import FileSerializer
from qfieldcloud.filestorage.view_helpers import (
    download_project_file_version,
    upload_project_file_version,
)
from rest_framework import permissions, status, views
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class PackageViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        try:
            project_id = request.parser_context["kwargs"].get("project_id")
            project = Project.objects.get(pk=project_id)
            return perms.can_access_project(request.user, project)
        except ObjectDoesNotExist:
            return False


class PackageUploadViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if not hasattr(request, "auth"):
            return False

        if request.auth.client_type != AuthToken.ClientType.WORKER:
            return False

        try:
            project_id = request.parser_context["kwargs"].get("project_id")
            job_id = request.parser_context["kwargs"].get("job_id")
            project = Project.objects.get(pk=project_id)

            if not perms.can_retrieve_project(request.user, project):
                return False

            # Check if the package job exists and it is already started, but not finished yet.
            # This is extra check that the request is coming from a currently active job.
            PackageJob.objects.get(
                id=job_id,
                status=PackageJob.Status.STARTED,
                project=project,
            )

            return True
        except ObjectDoesNotExist:
            return False


@extend_schema_view(
    get=extend_schema(
        description="Get all the files in a project package with files.",
        responses={200: LatestPackageSerializer()},
    ),
)
class LatestPackageView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, PackageViewPermissions]

    def get(self, request, project_id):
        """Get last project package status and file list."""
        project = get_object_or_404(Project, id=project_id)
        latest_finished_package_job = project.latest_finished_package_job_for_user(
            request.user
        )

        # Check if the project was packaged at least once
        if not latest_finished_package_job:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        files_qs = File.objects.filter(
            project_id=project_id,
            package_job=latest_finished_package_job,
            file_type=File.FileType.PACKAGE_FILE,
        )

        # get attachment files directly from the original project files, not from the package
        for attachment_dir in project.attachment_dirs:
            files_qs |= File.objects.filter(
                project_id=project_id,
                file_type=File.FileType.PROJECT_FILE,
                name__startswith=attachment_dir,
            )

        files_qs = files_qs.distinct()

        file_serializer = FileSerializer(files_qs, many=True)

        if not file_serializer.data:
            raise exceptions.InvalidJobError("Empty project package.")

        assert latest_finished_package_job.feedback

        feedback_version = latest_finished_package_job.feedback.get("feedback_version")
        # version 2 and 3 have the same format
        if feedback_version in ["2.0", "3.0"]:
            layers = latest_finished_package_job.feedback["outputs"][
                "qgis_layers_data"
            ]["layers_by_id"]
        # support some ancient QFieldCloud job data
        elif feedback_version is None:
            steps = latest_finished_package_job.feedback.get("steps", [])

            layers = None
            if len(steps) > 2 and steps[1].get("stage", 1) == 2:
                layers = steps[1]["outputs"]["layer_checks"]

        # be paranoid and raise for newer versions
        else:
            raise NotImplementedError()

        return Response(
            {
                "files": file_serializer.data,
                "layers": layers,
                "status": latest_finished_package_job.status,
                "package_id": latest_finished_package_job.pk,
                "packaged_at": latest_finished_package_job.project.data_last_packaged_at,
                "data_last_updated_at": latest_finished_package_job.project.data_last_updated_at,
            }
        )


@extend_schema_view(
    get=extend_schema(
        description="Download a file from a project package.",
        responses={
            (200, "*/*"): OpenApiTypes.BINARY,
        },
    ),
)
class LatestPackageDownloadFilesView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, PackageViewPermissions]

    def get(self, request, project_id, filename):
        """Download package file.

        Raises:
            exceptions.InvalidJobError: raised when packaging has never been triggered or successful for this project
        """
        project = get_object_or_404(Project, id=project_id)
        latest_finished_package_job = project.latest_finished_package_job_for_user(
            request.user
        )

        # Check if the project was packaged at least once
        if not latest_finished_package_job:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        # When the filename is in an attachment dir, we don't need to download the packaged files,
        # but the original project files. This optimization saves storage and time when packaging a project
        # with a lot of attachments, as the package job does not need to upload all these files in the package.
        if storage.get_attachment_dir_prefix(project, filename):
            file_type = File.FileType.PROJECT_FILE
        else:
            file_type = File.FileType.PACKAGE_FILE

        return download_project_file_version(
            request,
            project_id,
            filename,
            file_type=file_type,
            package_job_id=latest_finished_package_job.id,
        )


@extend_schema_view(
    post=extend_schema(
        description="Upload a file to the package",
        parameters=[
            OpenApiParameter(
                name="file",
                type=OpenApiTypes.BINARY,
                location=OpenApiParameter.QUERY,
                required=True,
                description="File to be uploaded",
            )
        ],
    )
)
class PackageUploadFilesView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, PackageUploadViewPermissions]

    def post(
        self, request: Request, project_id: UUID, job_id: UUID, filename: str
    ) -> Response:
        """Upload the package files."""
        uploaded_file_version = upload_project_file_version(
            request,
            project_id,
            filename,
            file_type=File.FileType.PACKAGE_FILE,
            package_job_id=job_id,
        )

        headers = {
            "Location": reverse(
                "filestorage_crud_file",
                kwargs={
                    "project_id": project_id,
                    "filename": filename,
                },
            ),
        }

        return Response(
            {
                "name": filename,
                "size": uploaded_file_version.size,
                "sha256": uploaded_file_version.sha256sum.hex(),
                "md5sum": uploaded_file_version.md5sum.hex(),
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )
