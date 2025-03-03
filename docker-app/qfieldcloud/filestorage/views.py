import logging
from uuid import UUID

from django.db.models import QuerySet
from django.http.response import HttpResponse, HttpResponseBase
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.core import (
    pagination,
    permissions_utils,
)
from qfieldcloud.core.models import (
    Project,
    UserAccount,
)
from qfieldcloud.filestorage.models import (
    File,
)
from qfieldcloud.core.views.files_views import (
    ListFilesView as LegacyFileListView,
    DownloadPushDeleteFileView as LegacyFileCrudView,
    ProjectMetafilesView as LegacyProjectMetaFileReadView,
)

from rest_framework import generics, permissions, serializers, status, views
from rest_framework.request import Request
from rest_framework.response import Response

from .serializers import FileWithVersionsSerializer
from .view_helpers import (
    delete_project_file_version,
    download_field_file,
    download_project_file_version,
    upload_project_file_version,
)

logger = logging.getLogger(__name__)


class FileListViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if "project_id" not in request.parser_context["kwargs"]:
            return False

        project_id = request.parser_context["kwargs"]["project_id"]
        project = Project.objects.get(id=project_id)

        return permissions_utils.can_read_files(request.user, project)


class FileCrudViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        if "project_id" not in request.parser_context["kwargs"]:
            return False

        project_id = request.parser_context["kwargs"]["project_id"]
        project = Project.objects.get(id=project_id)
        user = request.user

        if request.method == "GET":
            return permissions_utils.can_read_files(user, project)
        elif request.method == "DELETE":
            return permissions_utils.can_delete_files(user, project)
        elif request.method == "POST":
            return permissions_utils.can_create_files(user, project)

        return False


@extend_schema_view(
    get=extend_schema(
        description="Get all the project's file versions",
        responses={200: serializers.ListSerializer(child=FileWithVersionsSerializer())},
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
class FileListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, FileListViewPermissions]
    serializer_class = FileWithVersionsSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self, *args, **kwargs) -> QuerySet[File]:  # type: ignore
        project = get_object_or_404(Project, id=self.kwargs.get("project_id"))
        qs = File.objects.prefetch_related("versions").filter(
            project_id=project.id,
            file_type=File.FileType.PROJECT_FILE,
        )

        return qs


class FileCrudView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, FileCrudViewPermissions]

    def get(self, request: Request, project_id: UUID, filename: str):
        return download_project_file_version(
            request,
            project_id,
            filename,
            file_type=File.FileType.PROJECT_FILE,
        )

    def post(
        self, request: Request, project_id: UUID, filename: str, format=None
    ) -> Response:
        upload_project_file_version(
            request,
            project_id,
            filename,
            File.FileType.PROJECT_FILE,
        )

        headers = {
            "Location": reverse_lazy(
                "filestorage_crud_file",
                kwargs={
                    "project_id": project_id,
                    "filename": filename,
                },
            ),
        }

        return Response({}, status=status.HTTP_201_CREATED, headers=headers)

    def delete(self, request: Request, project_id: UUID, filename: str) -> Response:
        """Delete a file by filename in a project.

        This function deliberately does not check for project existance in advance to save a database query.
        The check is done anyways when we search for a file.

        Args:
            request (Request): the DRF request
            project_id (UUID): the project UUID
            filename (str): the filename to delete

        Returns:
            Response: empty response with 204
        """
        delete_project_file_version(request, project_id, filename)

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        description="Download the metadata of a project's file",
        responses={
            (200, "*/*"): OpenApiTypes.BINARY,
        },
    )
)
class ProjectMetaFileReadView(views.APIView):
    permission_classes = [
        permissions.IsAuthenticated,
        FileCrudViewPermissions,
    ]

    def get(self, request: Request, project_id: UUID) -> HttpResponseBase:
        project = get_object_or_404(Project, id=project_id)

        return download_field_file(
            request,
            project.thumbnail,
            "thumbnail.png",
        )


class AvatarFileReadView(views.APIView):
    permission_classes = []

    def get(self, request: Request, username: str) -> HttpResponseBase:
        useraccount = get_object_or_404(UserAccount, user__username=username)

        return download_field_file(
            request,
            useraccount.avatar,
            str(useraccount.avatar),
        )


@csrf_exempt
def compatibility_file_list_view(
    request: Request, *args, **kwargs
) -> Response | HttpResponse:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    # let's assume that `kwargs["project_id"]` will no throw a `KeyError`
    project_id: UUID = kwargs["project_id"]
    project = get_object_or_404(Project, id=project_id)
    view_kwargs = kwargs.pop("view_kwargs", {})

    if project.uses_legacy_storage:
        # rename the `project_id` to previously used `projectid`, so we don't change anything in the legacy code
        kwargs["projectid"] = kwargs.pop("project_id")

        logger.debug(f"Project {project_id=} will be using the legacy file management.")

        return LegacyFileListView.as_view(**view_kwargs)(request, *args, **kwargs)
    else:
        logger.debug(
            f"Project {project_id=} will be using the regular file management."
        )

        return FileListView.as_view(**view_kwargs)(request, *args, **kwargs)


@csrf_exempt
def compatibility_file_crud_view(
    request: Request, *args, **kwargs
) -> Response | HttpResponse:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    # let's assume that `kwargs["project_id"]` will no throw a `KeyError`
    project_id: UUID = kwargs["project_id"]
    project = get_object_or_404(Project, id=project_id)
    view_kwargs = kwargs.pop("view_kwargs", {})

    if project.uses_legacy_storage:
        # rename the `project_id` to previously used `projectid`, so we don't change anything in the legacy code
        kwargs["projectid"] = kwargs.pop("project_id")

        logger.debug(f"Project {project_id=} will be using the legacy file management.")

        return LegacyFileCrudView.as_view(**view_kwargs)(request, *args, **kwargs)
    else:
        logger.debug(
            f"Project {project_id=} will be using the regular file management."
        )

        return FileCrudView.as_view(**view_kwargs)(request, *args, **kwargs)


@csrf_exempt
def compatibility_project_meta_file_read_view(
    request: Request, *args, **kwargs
) -> Response | HttpResponse:
    """
    Todo:
        * Delete with QF-4963 Drop support for legacy storage
    """
    # let's assume that `kwargs["project_id"]` will no throw a `KeyError`
    project_id: UUID = kwargs["project_id"]
    project = get_object_or_404(Project, id=project_id)
    view_kwargs = kwargs.pop("view_kwargs", {})

    if project.uses_legacy_storage:
        # rename the `project_id` to previously used `projectid`, so we don't change anything in the legacy code
        kwargs["projectid"] = kwargs.pop("project_id")
        # hardcode the thumbnail file name
        kwargs["filename"] = kwargs.pop("thumbnail.png")

        logger.debug(
            f"Project {project_id=} will be using the legacy file management for meta files."
        )

        return LegacyProjectMetaFileReadView.as_view(**view_kwargs)(
            request, *args, **kwargs
        )
    else:
        logger.debug(
            f"Project {project_id=} will be using the regular file management for meta files."
        )

        return ProjectMetaFileReadView.as_view(**view_kwargs)(request, *args, **kwargs)
