import os
import json

from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.decorators import method_decorator

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.model.models import (
    Project, DeltaFile)
from qfieldcloud.apps.api.permissions import (
    ProjectPermission)
from qfieldcloud.apps.api.qgis_utils import apply_delta
from qfieldcloud.apps.api.serializers import DeltaFileSerializer
from qfieldcloud.apps.api.file_utils import get_sha256

User = get_user_model()


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List deltafiles of a project",
        operation_id="List deltafiles",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a deltafile to a project",
        operation_id="Add deltafile",))
class ListCreateDeltaFileView(generics.ListCreateAPIView):

    permission_classes = [IsAuthenticated, ProjectPermission]
    serializer_class = DeltaFileSerializer

    def post(self, request, projectid):

        try:
            project_obj = Project.objects.get(id=projectid)
        except Project.DoesNotExist:
            return Response(
                'Invalid project', status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.data:
            return Response(
                'Empty content', status=status.HTTP_400_BAD_REQUEST)

        request_file = request.data['file']

        try:
            delta_json = json.load(request_file)
        except ValueError:
            return Response(
                'DeltaFile is not a valid json file',
                status=status.HTTP_400_BAD_REQUEST)

        # Check if deltafile is already present in the database
        if DeltaFile.objects.filter(id=delta_json['id']).exists():
            df = DeltaFile.objects.get(id=delta_json['id'])
            if get_sha256(request_file) == get_sha256(df.file):
                return Response(status=status.HTTP_200_OK)
            else:
                return Response(
                    'A DeltaFile with the same id but different content already exists',
                    status=status.HTTP_400_BAD_REQUEST)

        delta_file_obj = DeltaFile.objects.create(
            id=delta_json['id'],
            project=project_obj,
            uploaded_by=request.user,
            file=request_file,
        )

        project_obj.export_to_filesystem()

        project_file = project_obj.get_qgis_project_file().original_path

        delta_file_obj.status = DeltaFile.STATUS_BUSY
        delta_file_obj.save()

        # TODO: Make this an asynchronous call
        response = apply_delta(
            str(project_obj.id),
            project_file,
            str(delta_file_obj.id))

        if response.status_code == 200:
            delta_file_obj.status = DeltaFile.STATUS_APPLIED
            delta_file_obj.save()
        else:
            try:
                output = response.json()['output']
                exit_code = response.json()['exit_code']

                if exit_code == 1:
                    delta_file_obj.status = DeltaFile.STATUS_APPLIED_WITH_CONFLICTS
                    delta_file_obj.output = output
                    delta_file_obj.save()
                else:
                    delta_file_obj.status = DeltaFile.STATUS_ERROR
                    delta_file_obj.output = output
                    delta_file_obj.save()

            except ValueError:
                delta_file_obj.status = DeltaFile.STATUS_ERROR
                delta_file_obj.save()

        return Response(status=status.HTTP_200_OK)

    def get_queryset(self):

        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)

        return DeltaFile.objects.filter(project=project_obj)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get delta status",
        operation_id="Get delta status",))
class GetDeltaView(generics.RetrieveAPIView):

    permission_classes = [IsAuthenticated, ProjectPermission]
    serializer_class = DeltaFileSerializer

    def get_object(self):
        deltafile_id = self.request.parser_context['kwargs']['deltafileid']
        return DeltaFile.objects.get(id=deltafile_id)
