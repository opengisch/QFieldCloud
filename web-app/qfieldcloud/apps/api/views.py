import os
from pathlib import Path
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.http import FileResponse
from django.utils.decorators import method_decorator

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.parsers import MultiPartParser
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.model.models import (
    Project, Organization, ProjectCollaborator)
from .serializers import (
    ProjectSerializer, CompleteUserSerializer,
    PublicInfoUserSerializer, OrganizationSerializer,
    ProjectCollaboratorSerializer, PushFileSerializer,
    ListFileSerializer)
from .permissions import (
    FilePermission, ProjectPermission, UserPermission)
from qfieldcloud.apps.model.models import File, FileVersion

User = get_user_model()


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List all users and organizations",
        operation_id="List users and organizations",))
class ListUsersView(generics.ListAPIView):

    serializer_class = PublicInfoUserSerializer

    def get_queryset(self):
        return User.objects.all()


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="""Get a single user's (or organization) publicly
        information or complete info if the request is done by the user
        himself""",
        operation_id="Get user",))
@method_decorator(
    name='put', decorator=swagger_auto_schema(
        operation_description="Update a user",
        operation_id="Update a user",))
@method_decorator(
    name='patch', decorator=swagger_auto_schema(
        operation_description="Patch a user",
        operation_id="Patch a user",))
class RetrieveUpdateUserView(generics.RetrieveUpdateAPIView):
    """Get or Update the authenticated user"""

    permission_classes = [UserPermission]
    serializer_class = CompleteUserSerializer

    def get_object(self):
        username = self.request.parser_context['kwargs']['username']
        return User.objects.get(username=username)

    def get(self, request, username):

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(
                'Invalid user', status=status.HTTP_400_BAD_REQUEST)

        if user.user_type == User.TYPE_ORGANIZATION:
            organization = Organization.objects.get(username=username)
            serializer = OrganizationSerializer(organization)
        else:
            if request.user == user:
                serializer = CompleteUserSerializer(user)
            else:
                serializer = PublicInfoUserSerializer(user)

        return Response(serializer.data)


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

    permission_classes = [ProjectPermission]
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

    permission_classes = [ProjectPermission]
    serializer_class = ProjectSerializer

    def get_object(self):

        project = self.request.parser_context['kwargs']['project']
        owner = self.request.parser_context['kwargs']['owner']
        owner_id = User.objects.get(username=owner)

        return Project.objects.get(name=project, owner=owner_id)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List project files",
        operation_id="List project files",))
class ListFilesView(generics.ListAPIView):

    permission_classes = [FilePermission]
    serializer_class = ListFileSerializer

    def get_queryset(self):
        owner = self.request.parser_context['kwargs']['owner']
        project = self.request.parser_context['kwargs']['project']

        owner_obj = User.objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        return File.objects.filter(project=project_obj)


class CreateRetrieveDestroyFileView(views.APIView):

    permission_classes = [FilePermission]
    parser_classes = [MultiPartParser]

    @swagger_auto_schema(
        operation_description="""Download a file, filename can also be a
        relative path, optional 'version' parameter for a specific version""",
        operation_id="Download a file",)
    def get(self, request, owner, project, filename):

        owner_obj = User.objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)
        version = None

        if 'version' in self.request.query_params:
            version = self.request.query_params['version']

        try:
            file = File.objects.get(
                original_path=filename, project=project_obj)
            pass
        except File.DoesNotExist:
            return Response(
                'File does not exist', status=status.HTTP_400_BAD_REQUEST)

        if version:
            response = FileResponse(
                file.get_version(version).stored_file,
                as_attachment=True,
                filename=filename)
        else:
            response = FileResponse(
                file.get_last_file_version().stored_file,
                as_attachment=True,
                filename=filename)

        return response

    @swagger_auto_schema(
        operation_description="""Delete a file, filename can also
        be a relative path""",
        operation_id="Delete a file",)
    def delete(self, request, owner, project, filename):

        owner_obj = User.objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        try:
            file = File.objects.get(
                original_path=filename, project=project_obj)
        except File.DoesNotExist:
            return Response(
                'File does not exist', status=status.HTTP_400_BAD_REQUEST)

        file.delete()

        return Response(status=status.HTTP_200_OK)

    @swagger_auto_schema(
        operation_description="""Push a file""",
        operation_id="Push a file", request_body=PushFileSerializer)
    def post(self, request, owner, project, filename, format=None):

        try:
            owner_obj = User.objects.get(username=owner)
            project_obj = Project.objects.get(name=project, owner=owner_obj)
        except User.DoesNotExist:
            return Response(
                'Invalid owner', status=status.HTTP_400_BAD_REQUEST)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.data:
            return Response(
                'Empty content', status=status.HTTP_400_BAD_REQUEST)

        # check only one qgs/qgz file per project
        if os.path.splitext(filename)[1].lower() in ['.qgs', '.qgz'] and \
           File.objects.filter(
               Q(project=project_obj),
               Q(original_path__iendswith='.qgs') |
               Q(original_path__iendswith='.qgz')):

            return Response(
                'Only one QGIS project per project allowed',
                status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        relative_path = filename

        # Check if the path is safe i.e. is not over the current directory
        if not Path('./').resolve() in Path(relative_path).resolve().parents:
            return Response('Invalid path', status=status.HTTP_400_BAD_REQUEST)

        request_file._name = relative_path

        if File.objects.filter(original_path=relative_path).exists():
            file_obj = File.objects.get(original_path=relative_path)

            # Update the updated_at field
            file_obj.save()

            FileVersion.objects.create(
                file=file_obj,
                stored_file=request_file,
                uploaded_by=request.user,
            )
        else:
            file_obj = File.objects.create(
                project=project_obj,
                original_path=relative_path,
            )

            FileVersion.objects.create(
                file=file_obj,
                stored_file=request_file,
                uploaded_by=request.user,
            )

        return Response(status=status.HTTP_201_CREATED)


class ListCollaboratorsView(generics.ListAPIView):
    """List collaborators of a project"""

    serializer_class = ProjectCollaboratorSerializer

    def get_queryset(self):
        owner = self.request.parser_context['kwargs']['owner']
        project = self.request.parser_context['kwargs']['project']

        owner_obj = User.objects.get(username=owner)
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
            'username': user.username,
        })
