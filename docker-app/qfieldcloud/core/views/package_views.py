import qfieldcloud.core.utils2 as utils2
from django.core.exceptions import ObjectDoesNotExist
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


class LatestPackageView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, PackageViewPermissions]

    def get(self, request, project_id):
        """Get last project package status and file list."""
        project = Project.objects.get(id=project_id)
        last_job = (
            PackageJob.objects.filter(
                project=project, status=PackageJob.Status.FINISHED
            )
            .order_by("started_at")
            .last()
        )

        # Check if the project was packaged at least once
        if not last_job:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        files = []
        for f in get_project_package_files(project_id):
            files.append(
                {
                    "name": f.name,
                    "size": f.size,
                    "last_modified": f.last_modified,
                    "sha256": check_s3_key(f.key),
                }
            )

        if not files:
            raise exceptions.InvalidJobError("Empty project package.")

        if last_job.feedback.get("feedback_version") == "2.0":
            layers = last_job.feedback["outputs"]["package_project"]["layer_checks"]
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
        last_job = PackageJob.objects.filter(
            project=project, status=PackageJob.Status.FINISHED
        ).latest("started_at")

        # Check if the project was packaged at least once
        if not last_job:
            raise exceptions.InvalidJobError(
                "Packaging has never been triggered or successful for this project."
            )

        key = utils.safe_join("projects/{}/export/".format(project_id), filename)

        return utils2.storage.file_response(
            request, key, presigned=True, expires=600, as_attachment=True
        )
