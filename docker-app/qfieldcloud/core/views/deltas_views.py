
import json
import jsonschema
from pathlib import PurePath

from django.contrib.auth import get_user_model
from django.utils.decorators import method_decorator
from django.core.exceptions import ObjectDoesNotExist

from rest_framework import status, views, permissions, generics
from rest_framework.response import Response

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.core.models import (
    Project, Deltafile)
from qfieldcloud.core import utils, permissions_utils
from qfieldcloud.core.serializers import DeltafileSerializer

User = get_user_model()


class DeltaFilePermissions(permissions.BasePermission):

    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(
            request, 'projectid')
        try:
            project = Project.objects.get(id=projectid)
        except ObjectDoesNotExist:
            return False
        user = request.user

        if request.method == 'GET':
            return permissions_utils.can_list_deltas(user, project)
        if request.method == 'POST':
            return permissions_utils.can_upload_deltas(user, project)
        return False


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List deltafiles of a project",
        operation_id="List deltafiles",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a deltafile to a project",
        operation_id="Add deltafile",))
class ListCreateDeltaFileView(generics.ListCreateAPIView):

    permission_classes = [permissions.IsAuthenticated,
                          DeltaFilePermissions]
    serializer_class = DeltafileSerializer

    def post(self, request, projectid):

        # TODO: check if projectid in the deltafile is the same as the
        # one of the request

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
            utils.get_deltafile_schema_validator().validate(delta_json)
        except (ValueError, jsonschema.exceptions.ValidationError) as e:
            return Response(
                'Not a valid deltafile: {}'.format(e),
                status=status.HTTP_400_BAD_REQUEST)

        deltafileid = delta_json['id']

        Deltafile.objects.create(
            id=deltafileid,
            project=project_obj,
            content=delta_json)

        sha256sum = utils.get_sha256(request_file)
        key = utils.safe_join(
            'projects/{}/deltas/'.format(projectid), deltafileid)

        # Check if deltafile is already present
        on_storage_sha = utils.check_s3_key(key)
        if on_storage_sha:
            if on_storage_sha == sha256sum:
                # TODO: Return status of the already applied deltafile
                return Response(status=status.HTTP_200_OK)
            else:
                return Response(
                    'A DeltaFile with the same id but different content already exists',
                    status=status.HTTP_400_BAD_REQUEST)

        bucket = utils.get_s3_bucket()
        metadata = {'Sha256sum': sha256sum}

        bucket.upload_fileobj(
            request_file.open(), key, ExtraArgs={"Metadata": metadata})

        project_file = utils.get_qgis_project_file(projectid)

        job = utils.apply_delta(
            str(project_obj.id),
            project_file,
            deltafileid,
            delta_json['id'])

        return Response({'jobid': job.id})

    def get_queryset(self):
        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)
        return Deltafile.objects.filter(project=project_obj)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get delta status",
        operation_id="Get delta status",))
class GetDeltaView(generics.RetrieveAPIView):

    permission_classes = [permissions.IsAuthenticated,
                          DeltaFilePermissions]
    serializer_class = DeltafileSerializer

    def get_object(self):

        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)
        deltafile_id = self.request.parser_context['kwargs']['deltafileid']

        return Deltafile.objects.get(id=deltafile_id, project=project_obj)
