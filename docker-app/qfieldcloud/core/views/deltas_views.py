import json
import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.translation import gettext as _
from qfieldcloud.core import exceptions, pagination, permissions_utils, utils
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


class ListCreateDeltasView(generics.ListCreateAPIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def post(self, request, projectid):

        project_obj = Project.objects.get(id=projectid)
        project_file = project_obj.project_filename

        if "file" not in request.data:
            raise exceptions.EmptyContentError()

        request_file = utils.strip_json_null_bytes(request.data["file"])
        created_deltas = []

        try:
            deltafile_json = json.load(request_file)
            utils.get_deltafile_schema_validator().validate(deltafile_json)

            deltafile_id = deltafile_json["id"]
            deltafile_projectid = deltafile_json["project"]

            deltas = deltafile_json.get("deltas", [])
            delta_ids = sorted([str(delta["uuid"]) for delta in deltas])
            existing_delta_ids = [
                str(v)
                for v in Delta.objects.filter(id__in=delta_ids)
                .order_by("id")
                .values_list("id", flat=True)
            ]

            if project_file is None:
                raise exceptions.NoQGISProjectError()

            if deltafile_projectid != str(projectid):
                exc = exceptions.DeltafileValidationError()
                exc.message = f"Deltafile's project id ({deltafile_projectid}) doesn't match URL parameter project id ({project_obj.id})."
                raise exc

            with transaction.atomic():
                for delta in deltas:
                    if delta["uuid"] in existing_delta_ids:
                        logger.warning(f'Duplicate delta id: ${delta["uuid"]}')
                        continue

                    delta_obj = Delta(
                        id=delta["uuid"],
                        deltafile_id=deltafile_id,
                        project=project_obj,
                        content=delta,
                        client_id=delta["clientId"],
                        created_by=self.request.user,
                    )

                    if not permissions_utils.can_create_delta(
                        self.request.user, delta_obj
                    ):
                        delta_obj.last_status = Delta.Status.UNPERMITTED
                        delta_obj.last_feedback = {
                            "msg": _(
                                "User has no rights to create delta on this project. Try inviting him as a collaborator with proper permissions and try again."
                            )
                        }
                    else:
                        delta_obj.last_status = Delta.Status.PENDING

                        if not delta_obj.project.owner_can_create_job:
                            delta_obj.last_feedback = {
                                "msg": _(
                                    "Some features of this project are not supported by the owner's account. Deltas are created but kept pending. Either upgrade the account or ensure you're not using features such as remote layers, then try again."
                                )
                            }

                    delta_obj.save(force_insert=True)
                    created_deltas.append(delta_obj)

        except Exception as err:
            if request_file:
                key = f"projects/{projectid}/deltas/{datetime.now().isoformat()}.json"
                # otherwise we upload an empty file
                request_file.seek(0)
                utils.get_s3_bucket().upload_fileobj(request_file, key)
                logger.info(f'Invalid deltafile saved as "{key}"')

            logger.exception(err)

            if isinstance(err, exceptions.NoQGISProjectError):
                raise err
            elif isinstance(err, exceptions.DeltafileValidationError):
                raise err
            else:
                raise exceptions.QFieldCloudException() from err

        if created_deltas and not jobs.apply_deltas(
            project_obj,
            self.request.user,
            project_file,
            project_obj.overwrite_conflicts,
        ):
            logger.warning("Failed to start delta apply job.")

        return Response()

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        return Delta.objects.filter(project=project_obj)


class ListDeltasByDeltafileView(generics.ListAPIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        deltafile_id = self.request.parser_context["kwargs"]["deltafileid"]
        return Delta.objects.filter(project=project_obj, deltafile_id=deltafile_id)


class ApplyView(views.APIView):

    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def post(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)
        project_file = project_obj.project_filename

        if project_file is None:
            raise exceptions.NoQGISProjectError()

        if not jobs.apply_deltas(
            project_obj,
            self.request.user,
            project_file,
            project_obj.overwrite_conflicts,
        ):
            logger.warning("Failed to start delta apply job.")

        return Response()
