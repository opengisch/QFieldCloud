from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.settings import api_settings

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.model.models import (
    Project, ProjectCollaborator)
from qfieldcloud.apps.api.serializers import (
    ProjectCollaboratorSerializer)
from qfieldcloud.apps.api.permissions import (
    CollaboratorPermission)

User = get_user_model()


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List collaborators of the project",
        operation_id="List collaborators",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a user as collaborator of the project",
        operation_id="Create collaborator",))
class ListCreateCollaboratorsView(generics.ListCreateAPIView):

    permission_classes = [CollaboratorPermission]
    serializer_class = ProjectCollaboratorSerializer

    def get_queryset(self):

        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)

        return ProjectCollaborator.objects.filter(project=project_obj)

    def post(self, request, projectid):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborator = User.objects.get(username=request.data['collaborator'])
        project = Project.objects.get(id=projectid)
        serializer.save(collaborator=collaborator, project=project)

        try:
            headers = {
                'Location': str(serializer.data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            headers = {}

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get the role of a collaborator",
        operation_id="Get collaborator",))
@method_decorator(
    name='put', decorator=swagger_auto_schema(
        operation_description="Update a collaborator",
        operation_id="Update collaborator",))
@method_decorator(
    name='patch', decorator=swagger_auto_schema(
        operation_description="Partial update collaborator",
        operation_id="Patch collaborator",))
@method_decorator(
    name='delete', decorator=swagger_auto_schema(
        operation_description="Remove a collaborator from a project",
        operation_id="Delete collaborator",))
class GetUpdateDestroyCollaboratorView(generics.RetrieveUpdateDestroyAPIView):

    permission_classes = [CollaboratorPermission]
    serializer_class = ProjectCollaboratorSerializer

    def get_object(self):
        project_id = self.request.parser_context['kwargs']['projectid']
        collaborator = self.request.parser_context['kwargs']['username']

        project_obj = Project.objects.get(id=project_id)
        collaborator_obj = User.objects.get(username=collaborator)
        return ProjectCollaborator.objects.get(
            project=project_obj,
            collaborator=collaborator_obj)
