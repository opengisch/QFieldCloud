import os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import FileUploadParser, MultiPartParser

from qfieldcloud.apps.model.models import Project #, ProjectRole
from . import permissions
from .serializers import (
    ProjectSerializer, FileSerializer, ProjectRoleSerializer)

from .permissions import IsProjectOwner
from qfieldcloud.apps.model.models import File


class RetrieveUserView(views.APIView):

    def get(self, request, username):
        """Get a single user (publicly information)"""
        # TODO: implement
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)


class ListUsersView(views.APIView):
    permission_classes = [IsProjectOwner]

    def get(self, request):
        """Get all users and organizations"""
        print("get list users")
        #return None
        # TODO: implement
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)


class RetrieveUpdateAuthenticatedUserView(views.APIView):

    def get(self, request):
        """Get the authenticated user"""
        # TODO: implement
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)

    def patch(self, request):
        """Update the authenticated user"""
        # TODO: implement
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)


class ListProjectsView(generics.ListAPIView):
    """List all public projects"""

    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(private=False)


class ListUserProjectsView(generics.GenericAPIView):

    def get(self, request):
        """List projects that the authenticated user has explicit permission
        to access"""

        # TODO: implement
        content = {'please move along': 'nothing to see here'}
        return Response(content, status=status.HTTP_501_NOT_IMPLEMENTED)


class ListCreateProjectView(generics.GenericAPIView):
    # TODO: check if user is allowed

    serializer_class = ProjectSerializer

    def get(self, request, owner):
        """List allowed projects of the specified user or organizazion"""

        owner_id = get_user_model().objects.get(username=owner)
        queryset = Project.objects.filter(owner=owner_id)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request, owner):
        """Create a new project"""
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


class RetrieveUpdateDestroyProjectView(generics.RetrieveUpdateDestroyAPIView):
    """Get, edit or delete project"""

    serializer_class = ProjectSerializer

    def get_object(self):
        # TODO: check if user is allowed

        project = self.request.parser_context['kwargs']['project']
        owner = self.request.parser_context['kwargs']['owner']
        owner_id = get_user_model().objects.get(username=owner)

        return Project.objects.get(name=project, owner=owner_id)


class PushFileView(views.APIView):

    # TODO: check if user is allowed
    # TODO: check only one qgs/qgz file per project

    parser_classes = [MultiPartParser]

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
            raise ParseError("Empty content")

        request_file = request.data['file']

        relative_dir = './'
        if 'path' in request.data:
            relative_dir = request.data['path']

        relative_path = os.path.join(relative_dir, request_file.name)

        # Check if the path is safe i.e. is not over the current directory
        if not Path('./').resolve() in Path(relative_path).resolve().parents:
            return Response('Invalid path', status=status.HTTP_400_BAD_REQUEST)

        request_file._name = relative_path

        file = File.objects.create(
            project=project_obj,
            stored_file=request_file,
        )

        file.save()

        return Response(status=status.HTTP_201_CREATED)


class ListFilesView(views.APIView):

    def get(self, request, owner, project):
        """List files in project"""

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        # TOCO: check if user is allowed to see
        # otherwise return Response(status=status.HTTP_403_FORBIDDEN)

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

    # TODO: check if user is allowed

    def get(self, request, owner, project, filename):
        """Download a file"""

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        file_path = str(project_obj.id) + '/' + filename

        file = File.objects.get(stored_file=file_path, project=project_obj)

        response = FileResponse(
            file.stored_file,
            as_attachment=True,
            filename=filename)
        return response

    # TODO: manage errors e.g. file not found and return a proper response

    def delete(self, request, owner, project, filename):
        """Delete a file"""

        owner_obj = get_user_model().objects.get(username=owner)
        project_obj = Project.objects.get(name=project, owner=owner_obj)

        file_path = str(project_obj.id) + '/' + filename

        file = File.objects.get(stored_file=file_path, project=project_obj)

        file.delete()

        return Response(status=status.HTTP_200_OK)


class ListCollaboratorsView(views.APIView):
    """List collaborators"""

    def get(self, request, owner, project):
        project_id = Project.objects.get(name=project)
        #p = ProjectRole.objects.filter(project=project_id)
        p = None
        result = []
        for _ in p:
            result.append(
                (str(_.user),
                 permissions.get_key_from_value(_.role)))
        return Response(result)


class CheckCreateDestroyCollaboratorView(views.APIView):
    """Check if a user is a collaborator"""

    serializer_class = ProjectRoleSerializer

    def post(self, request, owner, project, username):
        # TODO: check that logged user is either admin or owner

        user_id = get_user_model().objects.get(username=username)
        project_id = Project.objects.get(name=project)

        serializer = ProjectRoleSerializer(data=request.data)

        if serializer.is_valid():
            role = serializer.data['role']
            #ProjectRole.objects.create(user=user_id, project=project_id,
            #                           role=settings.PROJECT_ROLE[role])
            return Response(status=status.HTTP_200_OK)

        return Response(status=status.HTTP_400_BAD_REQUEST)

