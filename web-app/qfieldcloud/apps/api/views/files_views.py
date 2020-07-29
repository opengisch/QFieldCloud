import os

from pathlib import Path

from django.utils.decorators import method_decorator
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.http import FileResponse
from django.conf import settings

from rest_framework import generics, views, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser

from drf_yasg.utils import swagger_auto_schema
from drf_yasg.openapi import Parameter

from qfieldcloud.apps.api.serializers import (
    ListFileSerializer, PushFileSerializer)
from qfieldcloud.apps.api.permissions import FilePermission

from qfieldcloud.apps.model.models import (
    Project, File, FileVersion)

from qfieldcloud.apps.api import qgis_utils
from qfieldcloud.apps.api import file_utils

User = get_user_model()

client_parameter = Parameter(
    name='client', in_='query', type='string', enum=['qgis', 'qfield'],
    default='qfield')


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List project files",
        operation_id="List project files",
        manual_parameters=[client_parameter]))
class ListFilesView(views.APIView):

    permission_classes = [IsAuthenticated, FilePermission]

    def get(self, request, projectid):
        project_obj = None
        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        client = 'qfield'
        if 'client' in self.request.query_params:
            client = self.request.query_params['client']

        if client == 'qfield':
            return self._get_for_qfield(project_obj)
        elif client == 'qgis':
            return self._get_for_qgis(project_obj)
        else:
            return Response(
                'Client not valid',
                status=status.HTTP_400_BAD_REQUEST)

    def _get_for_qfield(self, project_obj):
        project_directory = os.path.join(
            settings.PROJECTS_ROOT,
            str(project_obj.id))

        export_directory = os.path.join(
            project_directory,
            'export')

        if not os.path.isdir(export_directory):
            project_file = project_obj.get_qgis_project_file()
            if project_file is None:
                return Response(
                    'The project does not contain a valid qgis project file',
                    status=status.HTTP_400_BAD_REQUEST)

            qgis_utils.export_project(str(project_obj.id),
                                      project_file.original_path)

        result = []
        for filename in os.listdir(export_directory):
            file = os.path.join(export_directory, filename)
            with open(file, 'rb') as f:
                result.append({
                    'name': filename,
                    'size': os.path.getsize(file),
                    'sha256': file_utils.get_sha256(f),
                })

        return Response(result)

    def _get_for_qgis(self, project_obj):
        serializer = ListFileSerializer(
            File.objects.filter(project=project_obj), many=True)
        return Response(serializer.data)


class DownloadPushDeleteFileView(views.APIView):

    permission_classes = [IsAuthenticated, FilePermission]
    parser_classes = [MultiPartParser]

    version_parameter = Parameter(
        name='version', in_='query', type='string',
        description='Require a specific version of the file. Only valid if client is `qgis`')

    @swagger_auto_schema(
        operation_description="""Download a file, filename can also be a
        relative path, optional 'version' parameter for a specific version""",
        operation_id="Download a file",
        manual_parameters=[client_parameter, version_parameter],
    )
    def get(self, request, projectid, filename):
        project_obj = None
        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        client = 'qfield'
        if 'client' in self.request.query_params:
            client = self.request.query_params['client']

        if client == 'qfield':
            return self._get_for_qfield(request, project_obj, filename)
        elif client == 'qgis':
            return self._get_for_qgis(request, project_obj, filename)
        else:
            return Response(
                'Client not valid',
                status=status.HTTP_400_BAD_REQUEST)

    def _get_for_qfield(self, request, project_obj, filename):
        project_obj.export_to_filesystem()
        project_directory = os.path.join(
            settings.PROJECTS_ROOT,
            str(project_obj.id))

        project_file = project_obj.get_qgis_project_file().original_path

        response = qgis_utils.export_project(str(project_obj.id), project_file)

        if not response.status_code == 200:
            return Response(
                response.json()['output'],
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return FileResponse(
            open(os.path.join(project_directory,
                              'export',
                              filename), 'rb'),
            as_attachment=True,
            filename=filename)

    def _get_for_qgis(self, request, project_obj, filename):
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
        operation_id="Delete a real file",)
    def delete(self, request, projectid, filename):

        project_obj = Project.objects.get(id=projectid)

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
        operation_id="Push a real file", request_body=PushFileSerializer)
    def post(self, request, projectid, filename, format=None):

        try:
            project_obj = Project.objects.get(id=projectid)
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
        if os.path.splitext(filename)[1].lower() in ['.qgs', '.qgz']:
            current_project_file = project_obj.get_qgis_project_file()
            if current_project_file is not None:
                # Allowed only to push the same project again
                if not filename == current_project_file.original_path:
                    return Response(
                        'Only one QGIS project per project allowed',
                        status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        relative_path = filename

        # Check if the path is safe i.e. is not over the current directory
        if not Path('./').resolve() in Path(relative_path).resolve().parents:
            return Response('Invalid path', status=status.HTTP_400_BAD_REQUEST)

        request_file._name = relative_path

        if File.objects.filter(
                original_path=relative_path, project=project_obj).exists():
            file_obj = File.objects.get(
                original_path=relative_path, project=project_obj)

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

        # If a qgs project is present in the project
        # we export the project's files on the file system with qfieldsync
        # se the list files (for qfield) API can use them.
        # We don't care about errors because
        # it could be that some files used by the project are still not
        # uploaded.
        # A best practice for a client will be to upload the qgs
        # file as the last uploaded file.
        current_project_file = project_obj.get_qgis_project_file()
        if current_project_file is not None:

            project_obj.export_to_filesystem()

            project_file = current_project_file.original_path
            qgis_utils.export_project(str(project_obj.id), project_file)

        return Response(status=status.HTTP_201_CREATED)
