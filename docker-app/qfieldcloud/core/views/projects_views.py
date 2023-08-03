from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.core import pagination, permissions_utils
from qfieldcloud.core.models import Project, ProjectQueryset
from qfieldcloud.core.serializers import ProjectSerializer
from qfieldcloud.core.utils2 import storage
from qfieldcloud.subscription.exceptions import QuotaError
from rest_framework import generics, permissions, viewsets

User = get_user_model()


class ProjectViewSetPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
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
        project = Project.objects.get(id=projectid)

        if view.action == "retrieve":
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
        parameters=[
            OpenApiParameter(
                name="include-public",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=0,
                enum=[1, 0],
                description="Include public projects",
            ),
        ],
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

    def get_queryset(self):
        projects = Project.objects.for_user(self.request.user)

        # In the list endpoint, by default we filter out public projects. They can be
        # included with the `include-public` query parameter.
        if self.action == "list":
            include_public = False
            include_public_param = self.request.query_params.get("include-public")
            if include_public_param and include_public_param.lower() == "1":
                include_public = True

            if not include_public:
                projects = projects.exclude(
                    user_role_origin=ProjectQueryset.RoleOrigins.PUBLIC
                )

        return projects

    @transaction.atomic
    def perform_update(self, serializer):
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
            return

        # Owner has changed, we must ensure he has enough quota for that
        # (in this transaction, the project is his already, so we just need to
        # check his quota)
        if new_owner.useraccount.storage_free_bytes < 0:
            # If not, we rollback the transaction
            # (don't give away numbers in message as it's potentially private)
            raise QuotaError("Project storage too large for recipient's quota.")

    def destroy(self, request, projectid):
        # Delete files from storage
        storage.delete_all_project_files_permanently(projectid)

        return super().destroy(request, projectid)


@extend_schema_view(get=extend_schema(description="List all public projects"))
class PublicProjectsListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ProjectSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        return Project.objects.for_user(self.request.user).filter(is_public=True)
