from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.core import pagination, permissions_utils
from qfieldcloud.core.models import Person, Project, ProjectCollaborator
from qfieldcloud.core.serializers import ProjectCollaboratorSerializer
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.settings import api_settings

User = get_user_model()


class ListCreateCollaboratorsViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        projectid = permissions_utils.get_param_from_request(request, "projectid")
        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            return permissions_utils.can_read_collaborators(user, project)
        if request.method == "POST":
            return permissions_utils.can_create_collaborators(user, project)
        return False


@extend_schema_view(
    get=extend_schema(description="Get all collaborators to the given project."),
    post=extend_schema(
        description="Add a user as collaborator to the project",
    ),
)
class ListCreateCollaboratorsView(generics.ListCreateAPIView):
    permission_classes = [
        permissions.IsAuthenticated,
        ListCreateCollaboratorsViewPermissions,
    ]
    serializer_class = ProjectCollaboratorSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)

        return ProjectCollaborator.objects.filter(project=project_obj)

    def post(self, request, projectid):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborator = Person.objects.get(username=request.data["collaborator"])
        project = Project.objects.get(id=projectid)
        serializer.save(
            collaborator=collaborator,
            project=project,
            created_by=request.user,
            updated_by=request.user,
        )

        try:
            headers = {"Location": str(serializer.data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            headers = {}

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class GetUpdateDestroyCollaboratorViewPermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        projectid = permissions_utils.get_param_from_request(request, "projectid")

        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            return False

        if request.method == "GET":
            return permissions_utils.can_read_collaborators(user, project)
        if request.method in ["PUT", "PATCH"]:
            return permissions_utils.can_update_collaborators(user, project)
        if request.method in ["DELETE"]:
            return permissions_utils.can_delete_collaborators(user, project)
        return False


@extend_schema_view(
    get=extend_schema(description="Get the role of a collaborator"),
    put=extend_schema(description="Update of a collaborator"),
    patch=extend_schema(description="Partial update of a collaborator"),
    delete=extend_schema(description="Remove a collaborator from the project"),
)
class GetUpdateDestroyCollaboratorView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [
        permissions.IsAuthenticated,
        GetUpdateDestroyCollaboratorViewPermissions,
    ]
    serializer_class = ProjectCollaboratorSerializer

    def get_object(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        collaborator = self.request.parser_context["kwargs"]["username"]

        project_obj = Project.objects.get(id=project_id)
        collaborator_obj = User.objects.get(username=collaborator)
        return ProjectCollaborator.objects.get(
            project=project_obj, collaborator=collaborator_obj
        )
