
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
    Project, Delta)
from qfieldcloud.core import utils, permissions_utils
from qfieldcloud.core.serializers import DeltaSerializer

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
        operation_description="List all deltas of a project",
        operation_id="List deltas",))
@method_decorator(
    name='post', decorator=swagger_auto_schema(
        operation_description="Add a deltafile to a project",
        operation_id="Add deltafile",))
class ListCreateDeltasView(generics.ListCreateAPIView):

    permission_classes = [permissions.IsAuthenticated,
                          DeltaFilePermissions]
    serializer_class = DeltaSerializer

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
            deltafile_json = json.load(request_file)
            utils.get_deltafile_schema_validator().validate(deltafile_json)
        except (ValueError, jsonschema.exceptions.ValidationError) as e:
            return Response(
                'Not a valid deltafile: {}'.format(e),
                status=status.HTTP_400_BAD_REQUEST)

        deltafile_id = deltafile_json['id']

        deltas = deltafile_json.get('deltas', [])
        for delta in deltas:
            Delta.objects.create(
                id=delta['uuid'],
                deltafile_id=deltafile_id,
                project=project_obj,
                content=delta,
            )

        project_file = utils.get_qgis_project_file(projectid)

        utils.apply_deltas(
            str(project_obj.id),
            project_file,
            project_obj.overwrite_conflicts
        )

        return Response()

    def get_queryset(self):
        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)
        return Delta.objects.filter(project=project_obj)


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="List deltas of a deltafile",
        operation_id="List deltas of deltafile",))
class ListDeltasByDeltafileView(generics.ListAPIView):

    permission_classes = [permissions.IsAuthenticated,
                          DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def get_queryset(self):
        project_id = self.request.parser_context['kwargs']['projectid']
        project_obj = Project.objects.get(id=project_id)
        deltafile_id = self.request.parser_context['kwargs']['deltafileid']
        return Delta.objects.filter(
            project=project_obj, deltafile_id=deltafile_id)
