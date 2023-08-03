from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions
from qfieldcloud.core import permissions_utils as perms
from qfieldcloud.core import utils
from qfieldcloud.core.models import PackageJob, Project
from qfieldcloud.core.serializers import LatestPackageSerializer
from qfieldcloud.core.utils import (
    check_s3_key,
    get_project_files,
    get_project_package_files,
)
from qfieldcloud.core.utils2 import storage
from rest_framework import permissions, views
from rest_framework.response import Response


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
        project = Project.objects.get(id=project_id)

        # Check if the project was packaged at least once
        if not project.last_package_job_id:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        filenames = set()
        files = []

        for f in get_project_package_files(project_id, project.last_package_job_id):
            filenames.add(f.name)
            files.append(
                {
                    "name": f.name,
                    "size": f.size,
                    "last_modified": f.last_modified,
                    "sha256": check_s3_key(f.key),
                    "md5sum": f.md5sum,
                    "is_attachment": False,
                }
            )

        # get attachment files directly from the original project files, not from the package
        for attachment_dir in project.attachment_dirs:
            for f in get_project_files(project_id, attachment_dir):
                # skip files that are part of the package
                if f.name in filenames:
                    continue

                filenames.add(f.name)
                files.append(
                    {
                        "name": f.name,
                        "size": f.size,
                        "last_modified": f.last_modified,
                        "sha256": check_s3_key(f.key),
                        "md5sum": f.md5sum,
                        "is_attachment": True,
                    }
                )

        if not files:
            raise exceptions.InvalidJobError("Empty project package.")

        last_job = project.last_package_job
        if last_job.feedback.get("feedback_version") == "2.0":
            layers = last_job.feedback["outputs"]["qgis_layers_data"]["layers_by_id"]
        else:
            steps = last_job.feedback.get("steps", [])
            layers = (
                steps[1]["outputs"]["layer_checks"]
                if len(steps) > 2 and steps[1].get("stage", 1) == 2
                else None
            )

        return Response(
            {
                "files": files,
                "layers": layers,
                "status": last_job.status,
                "package_id": last_job.pk,
                "packaged_at": last_job.project.data_last_packaged_at,
                "data_last_updated_at": last_job.project.data_last_updated_at,
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
            exceptions.InvalidJobError: [description]
        """
        project = Project.objects.get(id=project_id)

        # Check if the project was packaged at least once
        if not project.last_package_job_id:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        key = f"projects/{project_id}/packages/{project.last_package_job_id}/{filename}"

        # files within attachment dirs that do not exist is the packaged files should be served
        # directly from the original data storage
        if storage.get_attachment_dir_prefix(project, filename) and not check_s3_key(
            key
        ):
            key = f"projects/{project_id}/files/{filename}"

        # NOTE the `expires` kwarg is sending the `Expires` header to the client, keep it a low value (in seconds).
        return storage.file_response(
            request, key, presigned=True, expires=10, as_attachment=True
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

    def post(self, request, project_id, job_id, filename):
        """Upload the package files."""
        key = utils.safe_join(f"projects/{project_id}/packages/{job_id}/", filename)

        request_file = request.FILES.get("file")
        sha256sum = utils.get_sha256(request_file)
        md5sum = utils.get_md5sum(request_file)
        metadata = {"Sha256sum": sha256sum}

        bucket = utils.get_s3_bucket()
        bucket.upload_fileobj(request_file, key, ExtraArgs={"Metadata": metadata})

        return Response(
            {
                "name": filename,
                "size": request_file.size,
                "sha256": sha256sum,
                "md5sum": md5sum,
            }
        )
