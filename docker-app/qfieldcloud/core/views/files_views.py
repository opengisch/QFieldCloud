from pathlib import PurePath

import qfieldcloud.core.utils2 as utils2
from django.db import transaction
from django.utils import timezone
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import Job, ProcessProjectfileJob, Project
from qfieldcloud.core.utils import S3ObjectVersion, get_project_file_with_versions
from qfieldcloud.core.utils2.audit import LogEntry, audit
from qfieldcloud.core.utils2.storage import (
    get_attachment_dir_prefix,
    purge_old_file_versions,
)
from rest_framework import permissions, status, views
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response


class ListFilesViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if "projectid" not in request.parser_context["kwargs"]:
            return False

        projectid = request.parser_context["kwargs"]["projectid"]
        project = Project.objects.get(id=projectid)

        return permissions_utils.can_read_files(request.user, project)


class ListFilesView(views.APIView):
    # TODO: swagger doc
    # TODO: docstring

    permission_classes = [permissions.IsAuthenticated, ListFilesViewPermissions]

    def get(self, request, projectid):

        project = Project.objects.get(id=projectid)

        bucket = utils.get_s3_bucket()

        prefix = "projects/{}/files/".format(projectid)

        files = {}
        for version in bucket.object_versions.filter(Prefix=prefix):
            # Created the dict entry if doesn't exist
            if version.key not in files:
                files[version.key] = {"versions": []}

            head = version.head()
            path = PurePath(version.key)
            filename = str(path.relative_to(*path.parts[:3]))
            last_modified = version.last_modified.strftime("%d.%m.%Y %H:%M:%S %Z")

            # We cannot be sure of the metadata's first letter case
            # https://github.com/boto/boto3/issues/1709
            metadata = head["Metadata"]
            if "sha256sum" in metadata:
                sha256sum = metadata["sha256sum"]
            else:
                sha256sum = metadata["Sha256sum"]

            if version.is_latest:
                is_attachment = get_attachment_dir_prefix(project, filename) != ""

                files[version.key]["name"] = filename
                files[version.key]["size"] = version.size
                files[version.key]["sha256"] = sha256sum
                files[version.key]["md5sum"] = version.e_tag.replace('"', "")
                files[version.key]["last_modified"] = last_modified
                files[version.key]["is_attachment"] = is_attachment

            files[version.key]["versions"].append(
                {
                    "size": version.size,
                    "sha256": sha256sum,
                    "md5sum": version.e_tag.replace('"', ""),
                    "version_id": version.version_id,
                    "last_modified": last_modified,
                    "is_latest": version.is_latest,
                    "display": S3ObjectVersion(version.key, version).display,
                }
            )

        result_list = [files[key] for key in files]
        return Response(result_list)


class DownloadPushDeleteFileViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if "projectid" not in request.parser_context["kwargs"]:
            return False

        projectid = request.parser_context["kwargs"]["projectid"]
        project = Project.objects.get(id=projectid)
        user = request.user

        if request.method == "GET":
            return permissions_utils.can_read_files(user, project)
        if request.method == "DELETE":
            return permissions_utils.can_delete_files(user, project)
        if request.method == "POST":
            return permissions_utils.can_create_files(user, project)
        return False


class DownloadPushDeleteFileView(views.APIView):
    # TODO: swagger doc
    # TODO: docstring
    parser_classes = [MultiPartParser]
    permission_classes = [
        permissions.IsAuthenticated,
        DownloadPushDeleteFileViewPermissions,
    ]

    def get(self, request, projectid, filename):
        Project.objects.get(id=projectid)

        version = None
        if "version" in self.request.query_params:
            version = self.request.query_params["version"]

        key = utils.safe_join("projects/{}/files/".format(projectid), filename)
        return utils2.storage.file_response(
            request,
            key,
            presigned=True,
            expires=600,
            version=version,
            as_attachment=True,
        )

    # TODO refactor this function by moving the actual upload and Project model updates to library function outside the view
    def post(self, request, projectid, filename, format=None):
        project = Project.objects.get(id=projectid)

        if "file" not in request.data:
            raise exceptions.EmptyContentError()

        is_qgis_project_file = utils.is_qgis_project_file(filename)
        # check only one qgs/qgz file per project
        if (
            is_qgis_project_file
            and project.project_filename is not None
            and PurePath(filename) != PurePath(project.project_filename)
        ):
            raise exceptions.MultipleProjectsError(
                "Only one QGIS project per project allowed"
            )

        request_file = request.FILES.get("file")

        file_size_bytes = request_file.size
        quota_left_bytes = project.owner.useraccount.storage_free_bytes

        if file_size_bytes > quota_left_bytes:
            raise exceptions.QuotaError(
                f"Requiring {file_size_bytes} bytes of storage but only {quota_left_bytes} bytes available."
            )

        old_object = get_project_file_with_versions(project.id, filename)
        sha256sum = utils.get_sha256(request_file)
        bucket = utils.get_s3_bucket()

        key = utils.safe_join(f"projects/{projectid}/files/", filename)
        metadata = {"Sha256sum": sha256sum}

        bucket.upload_fileobj(request_file, key, ExtraArgs={"Metadata": metadata})

        new_object = get_project_file_with_versions(project.id, filename)

        assert new_object

        with transaction.atomic():
            # we only enter a transaction after the file is uploaded above because we do not
            # want to lock the project row for way too long. If we reselect for update the
            # project and update it now, it guarantees there will be no other file upload editing
            # the same project row.
            project = Project.objects.select_for_update().get(id=projectid)
            update_fields = ["data_last_updated_at", "file_storage_bytes"]

            if get_attachment_dir_prefix(project, filename) == "" and (
                is_qgis_project_file or project.project_filename is not None
            ):
                if is_qgis_project_file:
                    project.project_filename = filename
                    update_fields.append("project_filename")

                running_jobs = ProcessProjectfileJob.objects.filter(
                    project=project,
                    created_by=self.request.user,
                    status__in=[
                        Job.Status.PENDING,
                        Job.Status.QUEUED,
                        Job.Status.STARTED,
                    ],
                )

                if running_jobs.count() == 0:
                    ProcessProjectfileJob.objects.create(
                        project=project, created_by=self.request.user
                    )

            project.data_last_updated_at = timezone.now()
            # NOTE just incrementing the fils_storage_bytes when uploading might make the database out of sync if a files is uploaded/deleted bypassing this function
            project.file_storage_bytes += request_file.size
            project.save(update_fields=update_fields)

        if old_object:
            audit(
                project,
                LogEntry.Action.UPDATE,
                changes={filename: [old_object.latest.e_tag, new_object.latest.e_tag]},
            )
        else:
            audit(
                project,
                LogEntry.Action.CREATE,
                changes={filename: [None, new_object.latest.e_tag]},
            )

        # Delete the old file versions
        purge_old_file_versions(project)

        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request, projectid, filename):
        project = Project.objects.get(id=projectid)
        version_id = request.META.get("HTTP_X_FILE_VERSION")

        if version_id:
            utils2.storage.delete_project_file_version_permanently(
                project, filename, version_id, False
            )
        else:
            utils2.storage.delete_project_file_permanently(project, filename)

        return Response(status=status.HTTP_200_OK)


class ProjectMetafilesView(views.APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [
        permissions.IsAuthenticated,
        DownloadPushDeleteFileViewPermissions,
    ]

    def get(self, request, projectid, filename):
        key = utils.safe_join("projects/{}/meta/".format(projectid), filename)
        return utils2.storage.file_response(request, key, presigned=True)


class PublicFilesView(views.APIView):
    parser_classes = [MultiPartParser]
    permission_classes = []

    def get(self, request, filename):
        return utils2.storage.file_response(request, filename)
