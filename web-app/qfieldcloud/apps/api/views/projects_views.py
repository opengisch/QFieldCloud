from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.permissions import IsAuthenticated

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.model.models import (
    Project, ProjectCollaborator)
from qfieldcloud.apps.api.serializers import (
    ProjectSerializer)
from qfieldcloud.apps.api.permissions import (
    ListCreateProjectPermission, ProjectPermission)

User = get_user_model()

include_public_param = openapi.Parameter(
    'include-public', openapi.IN_QUERY,
    description="Include public projects",
    type=openapi.TYPE_BOOLEAN)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="""List projects owned by the authenticated
        user or that the authenticated user has explicit permission to access
        (i.e. she is a project collaborator)""",
        operation_id="List projects",
        manual_parameters=[include_public_param]))
class ListProjectsView(generics.ListAPIView):
    """List projects owned by the authenticated user or that she has
    explicit permission to access (i.e. she is a project collaborator)"""

    serializer_class = ProjectSerializer

    def get_queryset(self):
        if 'include-public' in self.request.query_params and \
           self.request.query_params['include-public'].lower() == 'true':
            qs = Project.objects.filter(owner=self.request.user) | \
                Project.objects.filter(
                    collaborators__in=ProjectCollaborator.objects.filter(
                        collaborator=self.request.user)) | \
                Project.objects.filter(private=False)
        else:
            qs = Project.objects.filter(owner=self.request.user) | \
                Project.objects.filter(
                    collaborators__in=ProjectCollaborator.objects.filter(
                        collaborator=self.request.user))
        return qs


class ListCreateProjectView(generics.GenericAPIView):

    permission_classes = [IsAuthenticated, ListCreateProjectPermission]
    serializer_class = ProjectSerializer

    @swagger_auto_schema(
        operation_description="""List all allowed projects of the specified
        user or organization""",
        operation_id="List projects of a user or organization",)
    def get(self, request, owner):

        # TODO: only allowed ones
        try:
            owner_id = User.objects.get(username=owner)
            queryset = Project.objects.filter(owner=owner_id)
        except User.DoesNotExist:
            return Response(
                'Invalid owner', status=status.HTTP_400_BAD_REQUEST)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="""Create a new project owned by the specified
        user or organization""",
        operation_id="Create a new project",)
    def post(self, request, owner):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner_id = User.objects.get(username=owner)
        serializer.save(owner=owner_id)

        try:
            headers = {
                'Location': str(serializer.data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            headers = {}

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get a project", operation_id="Get a project",))
@method_decorator(
    name='put', decorator=swagger_auto_schema(
        operation_description="Update a project",
        operation_id="Update a project",))
@method_decorator(
    name='patch', decorator=swagger_auto_schema(
        operation_description="Patch a project",
        operation_id="Patch a project",))
@method_decorator(
    name='delete', decorator=swagger_auto_schema(
        operation_description="Delete a project",
        operation_id="Delete a project",))
class RetrieveUpdateDestroyProjectView(generics.RetrieveUpdateDestroyAPIView):

    permission_classes = [IsAuthenticated, ProjectPermission]
    serializer_class = ProjectSerializer

    def get_object(self):

        project_id = self.request.parser_context['kwargs']['projectid']

        return Project.objects.get(id=project_id)
