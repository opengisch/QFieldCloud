import os
from pathlib import Path
from django.contrib.auth import get_user_model
from django.http import FileResponse
from django.utils.decorators import method_decorator

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.parsers import MultiPartParser
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.model.models import (
    Project, Organization, ProjectCollaborator)
from .serializers import (
    ProjectSerializer, CompleteUserSerializer,
    PublicInfoUserSerializer, OrganizationSerializer,
    ProjectCollaboratorSerializer, PushFileSerializer)
from .permissions import (FilePermission, ProjectPermission)
from qfieldcloud.apps.model.models import File


class RetrieveUserView(views.APIView):

    def get(self, request, username):
        """Get a single user's (or organization) publicly
        information or complete info if the request is done by the user"""

        try:
            user = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            return Response(
                'Invalid user', status=status.HTTP_400_BAD_REQUEST)

        if user.user_type == get_user_model().TYPE_ORGANIZATION:
            organization = Organization.objects.get(username=username)
            serializer = OrganizationSerializer(organization)
        else:
            if request.user == user:
                serializer = CompleteUserSerializer(user)
            else:
                serializer = PublicInfoUserSerializer(user)

        return Response(serializer.data)


class ListUsersView(generics.ListAPIView):
    """Get all users and organizations"""

    serializer_class = PublicInfoUserSerializer

    def get_queryset(self):
        return get_user_model().objects.all()


class RetrieveUpdateAuthenticatedUserView(generics.RetrieveUpdateAPIView):
    """Get or Update the authenticated user"""

    serializer_class = CompleteUserSerializer

    def get_object(self):
        return self.request.user


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List all public projects",
        operation_id="List public projects",))
class ListProjectsView(generics.ListAPIView):

    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(private=False)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="""List projects owned by the authenticated
        user or that the authenticated user has explicit permission to access
        (i.e. she is a project collaborator)""",
        operation_id="List current user's projects",))
class ListUserProjectsView(generics.ListAPIView):
    """List projects owned by the authenticated user or that she has
    explicit permission to access (i.e. she is a project collaborator)"""

    serializer_class = ProjectSerializer

    def get_queryset(self):

        qs = Project.objects.filter(owner=self.request.user) | \
            Project.objects.filter(
                collaborators__in=ProjectCollaborator.objects.filter(
                    collaborator=self.request.user))
        return qs


class ListCreateProjectView(generics.GenericAPIView):

    permission_classes = [ProjectPermission]
    serializer_class = ProjectSerializer

    @swagger_auto_schema(
        operation_description="""List all allowed projects of the specified
        user or organization""",
        operation_id="List projects of a user or organization",)
    def get(self, request, owner):

        # TODO: only allowed ones
        try:
            owner_id = get_user_model().objects.get(username=owner)
            queryset = Project.objects.filter(owner=owner_id)
        except get_user_model().DoesNotExist:
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
        owner_id = get_user_model().objects.get(username=owner)
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

    permission_classes = [ProjectPermission]
    serializer_class = ProjectSerializer

    def get_object(self):

        project = self.request.parser_context['kwargs']['project']
        owner = self.request.parser_context['kwargs']['owner']
        owner_id = get_user_model().objects.get(username=owner)

        return Project.objects.get(name=project, owner=owner_id)


class PushFileView(views.APIView):

    # TODO: check only one qgs/qgz file per project

    permission_classes = [FilePermission]
    parser_classes = [MultiPartParser]

    @swagger_auto_schema(
        operation_description="""Push a file in the root of the project
        or in a subdirectory if the path parameter is specified""",
        operation_id="Push a file", request_body=PushFileSerializer)
    def post(self, request, owner, project, format=None):

        try:
            owner_obj = get_user_model().objects.get(username=owner)
            project_obj = Project.objects.get(name=project, owner=owner_obj)
        except get_user_model().DoesNotExist:
            return Response(
                'Invalid owner', status=status.HTTP_400_BAD_REQUEST)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.data:
            return Response(
                'Empty content', status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        relative_dir = ''
        if 'path' in request.data:
            relative_dir = request.data['path']

        relative_path = os.path.join(relative_dir, request_file.name)

        # Check if the path is safe i.e. is not over the current directory
        if not Path('./').resolve() in Path(relative_path).resolve().parents:
            return Response('Invalid path', status=status.HTTP_400_BAD_REQUEST)

        request_file._name = relative_path

        stored_file = os.path.join(str(project_obj.id), request_file._name)

        if File.objects.filter(stored_file=stored_file).exists():
            # Update the updated_at field
            File.objects.get(stored_file=stored_file).save()
        else:
            File.objects.create(
                project=project_obj,
                stored_file=request_file,
            )

        return Response(status=status.HTTP_201_CREATED)


class ListFilesView(views.APIView):

    permission_classes = [FilePermission]

    def get(self, request, owner, project):
        """List files in project"""

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        files = File.objects.filter(project=project_obj)
        result = []
        for _ in files:
            result.append(
                {'name': _.filename(),
                 'size': _.stored_file.size,
                 'sha256': _.sha256(),
                 })
        return Response(result)


class RetrieveDestroyFileView(views.APIView):

    permission_classes = [FilePermission]

    @swagger_auto_schema(
        operation_description="""Download a file, filename can also be a
        relative path""",
        operation_id="Download a file",)
    def get(self, request, owner, project, filename):

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        file_path = os.path.join(str(project_obj.id), filename)

        try:
            file = File.objects.get(stored_file=file_path, project=project_obj)
        except File.DoesNotExist:
            return Response(
                'File does not exist', status=status.HTTP_400_BAD_REQUEST)

        response = FileResponse(
            file.stored_file,
            as_attachment=True,
            filename=filename)
        return response

    @swagger_auto_schema(
        operation_description="""Delete a file, filename can also
        be a relative path""",
        operation_id="Delete a file",)
    def delete(self, request, owner, project, filename):

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        file_path = os.path.join(str(project_obj.id), filename)

        try:
            file = File.objects.get(stored_file=file_path, project=project_obj)
        except File.DoesNotExist:
            return Response(
                'File does not exist', status=status.HTTP_400_BAD_REQUEST)

        file.delete()

        return Response(status=status.HTTP_200_OK)


class ListCollaboratorsView(generics.ListAPIView):
    """List collaborators of a project"""

    serializer_class = ProjectCollaboratorSerializer

    def get_queryset(self):
        owner = self.request.parser_context['kwargs']['owner']
        project = self.request.parser_context['kwargs']['project']

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        return ProjectCollaborator.objects.filter(project=project_obj)


class CheckCreateDestroyCollaboratorView(views.APIView):
    """Check if a user is a collaborator, add a user as a collaborator,
    remove a user as a collaborator"""

    # TODO: implement

    def get(self, request, owner, project, username):
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)

    def post(self, request, owner, project, username):
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)

    def delete(self, request, owner, project, username):
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)


class AuthToken(ObtainAuthToken):

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': user.username,
        })
