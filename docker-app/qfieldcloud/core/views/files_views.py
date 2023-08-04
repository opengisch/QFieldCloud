import copy
import io
import logging
from pathlib import PurePath
from traceback import print_stack

import qfieldcloud.core.utils2 as utils2
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import Job, ProcessProjectfileJob, Project
from qfieldcloud.core.serializers import FileSerializer
from qfieldcloud.core.utils import S3ObjectVersion, get_project_file_with_versions
from qfieldcloud.core.utils2.audit import LogEntry, audit
from qfieldcloud.core.utils2.sentry import report_serialization_diff_to_sentry
from qfieldcloud.core.utils2.storage import (
    get_attachment_dir_prefix,
    purge_old_file_versions,
)
from rest_framework import permissions, serializers, status, views
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class ListFilesViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if "projectid" not in request.parser_context["kwargs"]:
            return False

        projectid = request.parser_context["kwargs"]["projectid"]
        project = Project.objects.get(id=projectid)

        return permissions_utils.can_read_files(request.user, project)


@extend_schema_view(
    get=extend_schema(
        description="Get all the project's file versions",
        responses={200: serializers.ListSerializer(child=FileSerializer())},
        parameters=[
            OpenApiParameter(
                name="skip_metadata",
                type=OpenApiTypes.INT,
                required=False,
                default=0,
                enum=[1, 0],
                description="Skip obtaining file metadata (e.g. `sha256`). Makes responses much faster. In the future `skip_metadata=1` might be default behaviour.",
            ),
        ],
    ),
)
class ListFilesView(views.APIView):
    # TODO: docstring

    permission_classes = [permissions.IsAuthenticated, ListFilesViewPermissions]

    def get(self, request: Request, projectid: str) -> Response:
        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            raise NotFound(detail=projectid)

        bucket = utils.get_s3_bucket()
        prefix = f"projects/{projectid}/files/"

        files = {}
        for version in bucket.object_versions.filter(Prefix=prefix):
            # Created the dict entry if doesn't exist
            if version.key not in files:
                files[version.key] = {"versions": []}

            path = PurePath(version.key)
            filename = str(path.relative_to(*path.parts[:3]))
            last_modified = version.last_modified.strftime("%d.%m.%Y %H:%M:%S %Z")

            version_data = {
                "size": version.size,
                "md5sum": version.e_tag.replace('"', ""),
                "version_id": version.version_id,
                "last_modified": last_modified,
                "is_latest": version.is_latest,
                "display": S3ObjectVersion(version.key, version).display,
            }

            # NOTE Some clients (e.g. QField, QFieldSync) are still requiring the `sha256` key to check whether the files needs to be reuploaded.
            # Since we do not have control on these old client versions, we need to keep the API backward compatible for some time and assume `skip_metadata=0` by default.
            skip_metadata_param = request.GET.get("skip_metadata", "0")
            if skip_metadata_param == "0":
                skip_metadata = False
            else:
                skip_metadata = bool(skip_metadata_param)

            if not skip_metadata:
                head = version.head()
                # We cannot be sure of the metadata's first letter case
                # https://github.com/boto/boto3/issues/1709
                metadata = head["Metadata"]
                if "sha256sum" in metadata:
                    sha256sum = metadata["sha256sum"]
                else:
                    sha256sum = metadata["Sha256sum"]
                files[version.key]["sha256"] = sha256sum

                version_data["sha256"] = sha256sum

            if version.is_latest:
                is_attachment = get_attachment_dir_prefix(project, filename) != ""

                files[version.key]["name"] = filename
                files[version.key]["size"] = version.size
                files[version.key]["md5sum"] = version.e_tag.replace('"', "")
                files[version.key]["last_modified"] = last_modified
                files[version.key]["is_attachment"] = is_attachment

            files[version.key]["versions"].append(version_data)

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


@extend_schema_view(
    get=extend_schema(
        description="Download a file from a project",
        responses={
            (200, "*/*"): OpenApiTypes.BINARY,
        },
    ),
    post=extend_schema(
        description="Upload a file to the project",
        parameters=[
            OpenApiParameter(
                name="file",
                type=OpenApiTypes.BINARY,
                location=OpenApiParameter.QUERY,
                required=True,
                description="File to be uploaded",
            )
        ],
    ),
    delete=extend_schema(description="Delete a file from a project"),
)
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

        key = utils.safe_join(f"projects/{projectid}/files/", filename)
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

        if len(request.FILES.getlist("file")) > 1:
            raise exceptions.MultipleContentsError()

        # QF-2540
        # Getting traceback in case the traceback provided by Sentry is too short
        # Add post-serialization keys for diff-ing with pre-serialization keys
        buffer = io.StringIO()
        print_stack(limit=50, file=buffer)
        request_attributes = {
            "data": str(copy.copy(self.request.data).keys()),
            "files": str(self.request.FILES.keys()),
            "meta": str(self.request.META),
        }
        missing_error = ""

        if "file" not in request.data:
            missing_error = 'The key "file" was not found in `request.data`. Sending report to Sentry.'

        if not request.FILES.getlist("file"):
            missing_error = 'The key "file" occurs in `request.data` but maps to an empty list. Sending report to Sentry.'

        if missing_error:
            logging.warning(missing_error)

            # QF-2540
            report_serialization_diff_to_sentry(
                # using the 'X-Request-Id' added to the request by RequestIDMiddleware
                name=f"{request.META.get('X-Request-Id')}_{projectid}",
                pre_serialization=request.attached_keys,
                post_serialization=str(request_attributes),
                buffer=buffer,
            )
            raise exceptions.EmptyContentError()

        # get project from request or db
        if hasattr(request, "project"):
            project = request.project
        else:
            project = Project.objects.get(id=projectid)
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

        permissions_utils.check_can_upload_file(
            project, request.auth.client_type, request_file.size
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

                if not running_jobs.exists():
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

    @transaction.atomic()
    def delete(self, request, projectid, filename):
        project = Project.objects.select_for_update().get(id=projectid)
        version_id = request.META.get("HTTP_X_FILE_VERSION")

        if version_id:
            utils2.storage.delete_project_file_version_permanently(
                project, filename, version_id, False
            )
        else:
            utils2.storage.delete_project_file_permanently(project, filename)

        return Response(status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        description="Download the metadata of a project's file",
        responses={
            (200, "*/*"): OpenApiTypes.BINARY,
        },
    )
)
class ProjectMetafilesView(views.APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [
        permissions.IsAuthenticated,
        DownloadPushDeleteFileViewPermissions,
    ]

    def get(self, request, projectid, filename):
        key = utils.safe_join(f"projects/{projectid}/meta/", filename)
        return utils2.storage.file_response(request, key, presigned=True)


@extend_schema_view(
    get=extend_schema(
        description="Download a public file, e.g. user avatar.",
        responses={
            (200, "*/*"): OpenApiTypes.BINARY,
        },
    )
)
class PublicFilesView(views.APIView):
    parser_classes = [MultiPartParser]
    permission_classes = []

    def get(self, request, filename):
        return utils2.storage.file_response(request, filename)


@extend_schema(exclude=True)
class AdminDownloadPushDeleteFileView(DownloadPushDeleteFileView):
    """Allowing `DownloadPushDeleteFileView` to be excluded from the OpenAPI schema documentation"""


@extend_schema(exclude=True)
class AdminListFilesViews(ListFilesView):
    """Allowing `ListFilesView` to be excluded from the OpenAPI schema documentation"""
