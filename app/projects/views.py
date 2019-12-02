import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.settings import api_settings

from .models import Project, ProjectRole
from . import permissions
from .serializers import (
    ProjectSerializer, FileSerializer, ProjectRoleSerializer)


class ListProjectsView(generics.ListAPIView):
    """List all public projects"""

    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(private=False)


class ListUserProjectsView(views.APIView):

    def get(self, request):
        """List projects that the authenticated user has explicit permission to access"""


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

    serializer_class = FileSerializer

    def post(self, request, owner, project):
        """Upload one or more file/s"""

        username = request.user.username
        if not permissions.is_manager(
                username, project):

            return Response(status=status.HTTP_403_FORBIDDEN)

        for afile in request.FILES.getlist('file_content'):
            filename = os.path.join(
                settings.PROJECTS_ROOT,
                owner,
                project,
                afile.name)

            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "wb") as f:
                for chunk in afile.chunks():
                    f.write(chunk)

        return Response(status=status.HTTP_201_CREATED)


class ListFilesView(views.APIView):

    def get(self, request, owner, project):
        """List files in repository"""

        username = request.user.username
        if not permissions.is_reader(
                username, project):

            return Response(status=status.HTTP_403_FORBIDDEN)

        result = []

        dir_path = os.path.join(
            settings.PROJECTS_ROOT,
            owner,
            project)

        file_names = os.listdir(dir_path)

        for file_name in file_names:

            size = os.path.getsize(
                os.path.join(dir_path, file_name))

            hash = self.hashfile(
                os.path.join(dir_path, file_name))

            result.append(
                {'name': file_name,
                 'size': size,
                 'sha256': hash
                 })

        return Response(result)

    def hashfile(self, afile):
        """Return the sha256 hash of the passed file"""
        import hashlib
        BLOCKSIZE = 65536
        hasher = hashlib.sha256()
        with open(afile, 'rb') as f:
            buf = f.read(BLOCKSIZE)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(BLOCKSIZE)

        return hasher.hexdigest()


class RetrieveDestroyFileView(views.APIView):

    # TODO: check if user is allowed

    def get(self, request, owner, project, filename):
        """Download a file"""

        file_path = os.path.join(
            settings.PROJECTS_ROOT,
            owner,
            project,
            filename)

        response = FileResponse(
            open(file_path, 'rb'),
            as_attachment=True,
            filename=filename)
        return response
    # TODO: manage errors e.g. file not found and return a proper response

    def delete(self, request, owner, project, filename):
        """Delete a file"""

        file_path = os.path.join(
            settings.PROJECTS_ROOT,
            owner,
            project,
            filename)

        os.remove(file_path)
        # TODO: manage errors

        return Response(status=status.HTTP_200_OK)


class ListCollaboratorsView(views.APIView):
    """List collaborators"""

    def get(self, request, owner, project):
        project_id = Project.objects.get(name=project)
        p = ProjectRole.objects.filter(project=project_id)

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
            ProjectRole.objects.create(user=user_id, project=project_id,
                                       role=settings.PROJECT_ROLE[role])
            return Response(status=status.HTTP_200_OK)

        return Response(status=status.HTTP_400_BAD_REQUEST)
