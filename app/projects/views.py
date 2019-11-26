import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.settings import api_settings

from .models import Project
from .serializers import ProjectSerializer, FileSerializer


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

    # TODO: check if user is allowed

    serializer_class = FileSerializer

    def post(self, request, owner, project):
        """Upload one or more file/s"""
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

    # TODO: check if user is allowed
    def get(self, request, owner, repo):
        """List files in repository"""


class RetrieveDestroyFileView(views.APIView):

    # TODO: check if user is allowed

    def get(self, request, owner, project, filename):
        """Download a file"""

        #     def get(self, request, project_name):

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

    def delete(self, request, owner, repo, filename):
        """Delete a file"""
