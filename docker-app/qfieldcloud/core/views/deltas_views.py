import json
import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from qfieldcloud.core import exceptions, permissions_utils, utils
from qfieldcloud.core.models import Delta, Project
from qfieldcloud.core.serializers import DeltaSerializer
from qfieldcloud.core.utils2 import jobs
from rest_framework import generics, permissions, views
from rest_framework.response import Response

User = get_user_model()

logger = logging.getLogger(__name__)


class DeltaFilePermissions(permissions.BasePermission):
    def has_permission(self, request, view):
        projectid = permissions_utils.get_param_from_request(request, "projectid")
        project = Project.objects.get(id=projectid)
        user = request.user

        if request.method == "GET":
            return permissions_utils.can_read_deltas(user, project)
        if request.method == "POST":
            return permissions_utils.can_create_deltas(user, project)
        return False


@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="List all deltas of a project",
        operation_id="List deltas",
    ),
)
@method_decorator(
    name="post",
    decorator=swagger_auto_schema(
        operation_description="Add a deltafile to a project",
        operation_id="Add deltafile",
    ),
)
class ListCreateDeltasView(generics.ListCreateAPIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def post(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)
        project_file = utils.get_qgis_project_file(projectid)

        if "file" not in request.data:
            raise exceptions.EmptyContentError()

        request_file = request.data["file"]

        try:
            deltafile_json = json.load(request_file)
            utils.get_deltafile_schema_validator().validate(deltafile_json)

            deltafile_id = deltafile_json["id"]

            deltas = deltafile_json.get("deltas", [])

            if project_file is None:
                raise exceptions.NoQGISProjectError()

            with transaction.atomic():
                for delta in deltas:
                    delta_obj = Delta(
                        id=delta["uuid"],
                        deltafile_id=deltafile_id,
                        project=project_obj,
                        content=delta,
                        created_by=self.request.user,
                    )

                    if permissions_utils.can_create_delta(self.request.user, delta_obj):
                        delta_obj.last_status = Delta.Status.PENDING
                    else:
                        delta_obj.last_status = Delta.Status.UNPERMITTED

                    delta_obj.save(force_insert=True)

        except Exception as err:
            if request_file:
                key = f"projects/{projectid}/deltas/{datetime.now().isoformat()}.json"
                # otherwise we upload an empty file
                request_file.seek(0)
                utils.get_s3_bucket().upload_fileobj(request_file, key)

            logger.exception(err)

            if isinstance(err, IntegrityError):
                raise exceptions.DeltafileDuplicationError()
            else:
                raise exceptions.DeltafileValidationError()

        return Response()

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        return Delta.objects.filter(project=project_obj)


@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="List deltas of a deltafile",
        operation_id="List deltas of deltafile",
    ),
)
class ListDeltasByDeltafileView(generics.ListAPIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        deltafile_id = self.request.parser_context["kwargs"]["deltafileid"]
        return Delta.objects.filter(project=project_obj, deltafile_id=deltafile_id)


@method_decorator(
    name="post",
    decorator=swagger_auto_schema(
        operation_description="Trigger apply delta",
        operation_id="Apply delta",
    ),
)
class ApplyView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def post(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)
        project_file = utils.get_qgis_project_file(projectid)

        if project_file is None:
            raise exceptions.NoQGISProjectError()

        if not jobs.apply_deltas(
            project_obj,
            self.request.user,
            project_file,
            project_obj.overwrite_conflicts,
        ):
            raise exceptions.NoDeltasToApplyError()

        return Response()
