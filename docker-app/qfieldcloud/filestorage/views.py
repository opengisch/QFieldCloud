import logging
from uuid import UUID

from django.contrib.staticfiles.storage import staticfiles_storage
from django.db.models import Q, QuerySet
from django.http.response import HttpResponse, HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, permissions, serializers, status, views
from rest_framework.request import Request
from rest_framework.response import Response

from qfieldcloud.core import (
    pagination,
    permissions_utils,
    utils2,
)
from qfieldcloud.core.models import (
    Project,
    UserAccount,
)
from qfieldcloud.core.views.files_views import (
    DownloadPushDeleteFileView as LegacyFileCrudView,
)
from qfieldcloud.core.views.files_views import (
    ListFilesView as LegacyFileListView,
)
from qfieldcloud.core.views.files_views import (
    ProjectMetafilesView as LegacyProjectMetaFileReadView,
)
from qfieldcloud.filestorage.models import (
    File,
)

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

        qs = (
            File.objects.select_related(
                # NOTE needed as we check `get_attachment_dir_prefix(project)` for each file
                "project",
                # NOTE needed as we add the `latest_version`'s timestamp
                "latest_version",
            )
            .prefetch_related(
                # NOTE the `versions` default queryset automatically does `select_related("file")`
                "versions"
            )
            .filter(
                project_id=project.id,
                file_type=File.FileType.PROJECT_FILE,
            )
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
            "Location": reverse(
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
            request: the DRF request
            project_id: the project UUID
            filename: the filename to delete

        Returns:
            empty response with 204
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
        project = get_object_or_404(
            Project, Q(id=project_id) & Q(thumbnail__isnull=False) & ~Q(thumbnail="")
        )

        return download_field_file(
            request,
            project.thumbnail,
            "thumbnail.png",
        )


class AvatarFileReadView(views.APIView):
    permission_classes = []

    def get(
        self, request: Request, username: str, filename: str = ""
    ) -> HttpResponseBase:
        """Returns an internal redirect within nginx to serve the `avatar` file directly from the Object Storage.

        NOTE the filename field is completely ignored and redundant, it exists only to satisfy backwards compatible expectations in QField/QFieldSync that avatars will have filename with file extension.
        Args:
            request: incoming request
            username: the username we are serving avatar for
            filename: the filename in the URL, but ignored in the function execution. Defaults to "".

        Returns:
            internal redirect to the Object Storage
        """
        useraccount = get_object_or_404(UserAccount, user__username=username)

        if useraccount.avatar:
            return download_field_file(
                request,
                useraccount.avatar,
                str(useraccount.avatar),
            )
        else:
            if useraccount.legacy_avatar_uri:
                return utils2.storage.file_response(
                    request._request,
                    useraccount.legacy_avatar_uri,
                )
            else:
                return redirect(staticfiles_storage.url("logo.svg"))


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
        kwargs["filename"] = "thumbnail.png"

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
