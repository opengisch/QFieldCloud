from pathlib import PurePath

from django.http.response import HttpResponseRedirect
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import Project
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

        return HttpResponseRedirect(url)

    def post(self, request, projectid, filename, format=None):

        Project.objects.get(id=projectid)

        if "file" not in request.data:
            raise exceptions.EmptyContentError()

        # check only one qgs/qgz file per project
        if filename.lower().endswith(".qgs") or filename.lower().endswith(".qgz"):
            current_project_file = utils.get_qgis_project_file(projectid)
            if current_project_file is not None:
                # Allowed only to push the a new version of the same file
                if not PurePath(filename) == PurePath(current_project_file):
                    raise exceptions.MultipleProjectsError(
                        "Only one QGIS project per project allowed"
                    )

        request_file = request.FILES.get("file")

        sha256sum = utils.get_sha256(request_file)
        bucket = utils.get_s3_bucket()

        key = utils.safe_join("projects/{}/files/".format(projectid), filename)
        metadata = {"Sha256sum": sha256sum}

        bucket.upload_fileobj(request_file, key, ExtraArgs={"Metadata": metadata})

        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request, projectid, filename):

        Project.objects.get(id=projectid)

        key = utils.safe_join("projects/{}/files/".format(projectid), filename)
        bucket = utils.get_s3_bucket()

        bucket.object_versions.filter(Prefix=key).delete()

        return Response(status=status.HTTP_200_OK)
