from pathlib import Path
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404, StreamingHttpResponse
from django_filters import rest_framework as filters
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.core import pagination, permissions_utils
from qfieldcloud.core.drf_utils import QfcOrderingFilter
from qfieldcloud.core.exceptions import ObjectNotFoundError
from qfieldcloud.core.filters import ProjectFilterSet
from qfieldcloud.core.models import Project, ProjectQueryset, ProjectSeed
from qfieldcloud.core.serializers import ProjectSeedSerializer, ProjectSerializer
from qfieldcloud.core.utils2 import storage
from qfieldcloud.subscription.exceptions import QuotaError
from rest_framework import filters as drf_filters
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

User = get_user_model()


class ProjectViewSetPermissions(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        if view.action is None:
            # If `view.action` is `None`, means that we are getting a OPTIONS request.
            # We don't know what it is, so we deny permission.
            return False

        if view.action == "list":
            # The queryset is already filtered by what the user can see
            return True

        user = request.user
        owner = permissions_utils.get_param_from_request(request, "owner")

        if owner:
            owner_obj = User.objects.get(username=owner)
        else:
            # If the owner is not in the request, means that the owner
            # should be the user that made the request
            owner_obj = user

        if view.action == "create":
            return permissions_utils.can_create_project(user, owner_obj)

        projectid = permissions_utils.get_param_from_request(request, "projectid")

        try:
            project = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            raise ObjectNotFoundError(detail="Project not found.")

        if view.action == "retrieve":
            return permissions_utils.can_retrieve_project(user, project)
        elif view.action == "seed":
            return permissions_utils.can_retrieve_project(user, project)
        elif view.action == "seed_xlsform":
            return permissions_utils.can_retrieve_project(user, project)
        elif view.action == "destroy":
            return permissions_utils.can_delete_project(user, project)
        elif view.action in ["update", "partial_update"]:
            return permissions_utils.can_update_project(user, project)

        return False


@extend_schema_view(
    retrieve=extend_schema(description="Retrieve a project"),
    update=extend_schema(description="Update a project"),
    partial_update=extend_schema(description="Partially update a project"),
    destroy=extend_schema(description="Delete a project"),
    list=extend_schema(
        description="""List projects owned by the authenticated
        user or that the authenticated user has explicit permission to access
        (i.e. she is a project collaborator)""",
    ),
    create=extend_schema(
        description="""Create a new project owned by the specified
        user or organization"""
    ),
)
class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    lookup_url_kwarg = "projectid"
    permission_classes = [permissions.IsAuthenticated, ProjectViewSetPermissions]
    pagination_class = pagination.QfcLimitOffsetPagination()
    filter_backends = [
        drf_filters.SearchFilter,
        filters.DjangoFilterBackend,
        QfcOrderingFilter,
    ]
    search_fields = ["owner__username", "name"]
    filterset_class = ProjectFilterSet
    ordering_fields = ["owner__username::alias=owner", "name", "created_at"]

    def get_queryset(self):
        projects = Project.objects.for_user(self.request.user)

        if self.action == "list":
            # In the list endpoint, by default we filter out public projects.
            # They can be included with the `include_public` query parameter or
            # the deprecated `include-public` query parameter.
            force_exclude_public = True
            include_public_param = self.request.query_params.get("include-public")
            if include_public_param and include_public_param != "":
                force_exclude_public = False

            include_public_param = self.request.query_params.get("include_public")
            if include_public_param and include_public_param != "":
                force_exclude_public = False

            if force_exclude_public:
                projects = projects.exclude(
                    user_role_origin=ProjectQueryset.RoleOrigins.PUBLIC
                )

        projects = projects.order_by("-is_featured", "owner__username", "name")

        return projects

    @transaction.atomic
    def perform_update(self, serializer: ProjectSerializer) -> None:
        # Here we do an additional check if the owner has changed. If so, the reciever
        # of the project must have enough storage quota, otherwise the transfer is
        # not permitted.

        # TODO: this should be moved to some more reusable place. Maybe in Project.clean() ?
        # But then it would also be enforced by admin, which we don't want I guess...

        old_owner = serializer.instance.owner
        super().perform_update(serializer)
        new_owner = serializer.instance.owner

        # If owner has not changed, no additional check is made
        if old_owner == new_owner:
            return None

        # Owner has changed, we must ensure he has enough quota for that
        # (in this transaction, the project is his already, so we just need to
        # check his quota)
        if new_owner.useraccount.storage_free_bytes < 0:
            # If not, we rollback the transaction
            # (don't give away numbers in message as it's potentially private)
            raise QuotaError("Project storage too large for recipient's quota.")

    def destroy(self, request, projectid):
        # Delete files from storage
        project = Project.objects.get(id=projectid)

        if project.uses_legacy_storage:
            storage.delete_all_project_files_permanently(projectid)

        return super().destroy(request, projectid)

    @action(detail=True, methods=["get"])
    def seed(self, _request: Request, projectid: UUID):
        project = ProjectSeed.objects.select_related("project").get(
            project_id=projectid
        )

        return Response(ProjectSeedSerializer(project).data)

    @action(detail=True, methods=["get"], url_path="seed/xlsform")
    def seed_xlsform(self, request: Request, projectid: UUID) -> StreamingHttpResponse:
        project = Project.objects.select_related("seed").get(id=projectid)

        if not project.seed.xlsform_file:
            raise Http404("Project has no XLSForm file.")

        xlsform_file = project.seed.xlsform_file
        extension = Path(xlsform_file.name).suffix.lower()

        return StreamingHttpResponse(
            xlsform_file,
            content_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="xlsform{extension}"',
            },
        )


@extend_schema_view(get=extend_schema(description="List all public projects"))
class PublicProjectsListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProjectSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()
    filter_backends = [QfcOrderingFilter]
    ordering_fields = ["owner__username::alias=owner", "name", "created_at"]

    def get_queryset(self):
        return (
            Project.objects.for_user(self.request.user)
            .filter(is_public=True)
            .order_by("-is_featured", "owner__username", "name")
        )
