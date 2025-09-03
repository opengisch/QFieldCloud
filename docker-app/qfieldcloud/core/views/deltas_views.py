import json
import logging
from traceback import format_exception
from typing import IO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from qfieldcloud.core import exceptions, pagination, permissions_utils, utils
from qfieldcloud.core.models import Delta, FaultyDeltaFile, Project
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
        elif request.method == "POST":
            return permissions_utils.can_create_deltas(user, project)

        return False


@extend_schema_view(
    get=extend_schema(description="Get all deltas of the given project."),
    post=extend_schema(
        description="Add a deltafile to the given project",
        parameters=[
            OpenApiParameter(
                name="file",
                type=OpenApiTypes.BINARY,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Deltafille to be uploaded.",
            ),
        ],
        request=None,
        responses={
            200: OpenApiTypes.NONE,
        },
    ),
)
class ListCreateDeltasView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def post(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)

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

            if not project_obj.has_the_qgis_file:
                raise exceptions.NoQGISProjectError()

            if deltafile_projectid != str(projectid):
                exc = exceptions.DeltafileValidationError()
                exc.message = f"Deltafile's project id ({deltafile_projectid}) doesn't match URL parameter project id ({project_obj.id})."
                raise exc

            with transaction.atomic():
                for delta in deltas:
                    if delta["uuid"] in existing_delta_ids:
                        logger.warning(f"Duplicate delta id: ${delta['uuid']}")
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
                self.preserve_faulty_deltafile(
                    request_file, project_obj, self.request, err
                )

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
            project_obj.the_qgis_file_name,
            project_obj.overwrite_conflicts,
        ):
            logger.warning("Failed to start delta apply job.")

        return Response()

    def preserve_faulty_deltafile(
        self, request_file: IO, project: Project, request: HttpRequest, err: Exception
    ) -> FaultyDeltaFile:
        """Preserve a faulty deltafile for later inspection."""
        # File contents might already have been partially read by JSON parser.
        # Rewind to avoid uploading an empty file.
        request_file.seek(0)
        deltafile_data = request_file.read()

        # Be defensive about figuring out the deltafile id - we might not
        # even have a valid JSON file.
        try:
            deltafile_json = json.loads(deltafile_data)
            deltafile_id = deltafile_json.get("id")
        except Exception:
            deltafile_id = None

        name = deltafile_id if deltafile_id else "unkown"
        filename = f"{name}.json"

        user_agent = request.headers.get("user-agent")

        faulty_deltafile = FaultyDeltaFile.objects.create(
            deltafile=ContentFile(deltafile_data, filename),
            project=project,
            user_agent=user_agent,
            traceback="".join(format_exception(err)),
            deltafile_id=deltafile_id,
        )

        logger.info(f'Faulty deltafile saved as "{faulty_deltafile.deltafile.name}"')
        return faulty_deltafile

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        return Delta.objects.filter(project=project_obj)


@extend_schema_view(
    get=extend_schema(description="List deltas of the given deltafile.")
)
class ListDeltasByDeltafileView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer
    pagination_class = pagination.QfcLimitOffsetPagination()

    def get_queryset(self):
        project_id = self.request.parser_context["kwargs"]["projectid"]
        project_obj = Project.objects.get(id=project_id)
        deltafile_id = self.request.parser_context["kwargs"]["deltafileid"]
        return Delta.objects.filter(project=project_obj, deltafile_id=deltafile_id)


@extend_schema(
    deprecated=True,
    summary="This endpoint is deprecated and will be removed in the future. Please use `/jobs/` endpoint instead.",
)
@extend_schema_view(post=extend_schema(description="Trigger apply delta."))
class ApplyView(views.APIView):
    permission_classes = [permissions.IsAuthenticated, DeltaFilePermissions]
    serializer_class = DeltaSerializer

    def post(self, request, projectid):
        project_obj = Project.objects.get(id=projectid)
        project_file = project_obj.the_qgis_file_name

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
