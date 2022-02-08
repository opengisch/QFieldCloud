from pathlib import PurePath

from django.http.response import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import ProcessProjectfileJob, Project
from qfieldcloud.core.utils import S3ObjectVersion, get_project_file_with_versions
from qfieldcloud.core.utils2.audit import LogEntry, audit
from qfieldcloud.core.utils2.storage import purge_old_file_versions, staticfile_prefix
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

        Project.objects.get(id=projectid)

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
                files[version.key]["name"] = filename
                files[version.key]["size"] = version.size
                files[version.key]["sha256"] = sha256sum
                files[version.key]["last_modified"] = last_modified

            files[version.key]["versions"].append(
                {
                    "size": version.size,
                    "sha256": sha256sum,
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

        extra_args = {}
        if "version" in self.request.query_params:
            version = self.request.query_params["version"]
            extra_args["VersionId"] = version

        filekey = utils.safe_join("projects/{}/files/".format(projectid), filename)

        url = utils.get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                **extra_args,
                "Key": filekey,
                "Bucket": utils.get_s3_bucket().name,
                "ResponseContentType": "application/force-download",
                "ResponseContentDisposition": f'attachment;filename="{filename}"',
            },
            ExpiresIn=600,
            HttpMethod="GET",
        )

        if request.META.get("HTTP_HOST", "").split(":")[-1] == request.META.get(
            "WEB_HTTPS_PORT"
        ):
            # Let's NGINX handle the redirect to the storage and streaming the file contents back to the client
            response = HttpResponse()
            response["X-Accel-Redirect"] = "/storage-download/"
            response["redirect_uri"] = url

            return response
        else:
            # requesting the Django development webserver
            return HttpResponseRedirect(url)

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
        old_object = get_project_file_with_versions(project.id, filename)
        sha256sum = utils.get_sha256(request_file)
        bucket = utils.get_s3_bucket()

        key = utils.safe_join(f"projects/{projectid}/files/", filename)
        metadata = {"Sha256sum": sha256sum}

        bucket.upload_fileobj(request_file, key, ExtraArgs={"Metadata": metadata})

        new_object = get_project_file_with_versions(project.id, filename)

        assert new_object

        if staticfile_prefix(project, filename) == "" and (
            is_qgis_project_file or project.project_filename is not None
        ):
            if is_qgis_project_file:
                project.project_filename = filename

            ProcessProjectfileJob.objects.create(
                project=project, created_by=self.request.user
            )

        project.data_last_updated_at = timezone.now()
        project.save()

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
        key = utils.safe_join(f"projects/{projectid}/files/", filename)
        bucket = utils.get_s3_bucket()

        old_object = get_project_file_with_versions(project.id, filename)

        assert old_object

        bucket.object_versions.filter(Prefix=key).delete()

        if utils.is_qgis_project_file(filename):
            project.project_filename = None
            project.save()

        audit(
            project,
            LogEntry.Action.DELETE,
            changes={filename: [old_object.latest.e_tag, None]},
        )

        return Response(status=status.HTTP_200_OK)
