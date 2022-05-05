import qfieldcloud.core.utils2 as utils2
from django.core.exceptions import ObjectDoesNotExist
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import PackageJob, Project
from qfieldcloud.core.utils import check_s3_key, get_project_package_files
from rest_framework import permissions, views
from rest_framework.response import Response


class PackageViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        try:
            project_id = request.parser_context["kwargs"].get("project_id")
            project = Project.objects.get(pk=project_id)
            return permissions_utils.can_read_project(request.user, project)
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
            if not permissions_utils.can_update_project(request.user, project):
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

        files = []
        for f in get_project_package_files(project_id, project.last_package_job_id):
            files.append(
                {
                    "name": f.name,
                    "size": f.size,
                    "last_modified": f.last_modified,
                    "sha256": check_s3_key(f.key),
                    "md5sum": f.md5sum,
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

        key = utils.safe_join(
            f"projects/{project_id}/packages/{project.last_package_job_id}/", filename
        )

        return utils2.storage.file_response(
            request, key, presigned=True, expires=600, as_attachment=True
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
