from django.db import transaction
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.authentication.authentication import WorkerPoolAuthentication
from qfieldcloud.core.exceptions import WorkerPoolKeyAlreadySetError
from qfieldcloud.core.models import WorkerPool
from qfieldcloud.core.sealed_box import SealedBoxError, validate_public_key
from qfieldcloud.core.worker_pools import claim_job
from rest_framework import permissions, serializers, status, views
from rest_framework.request import Request
from rest_framework.response import Response


class IsWorkerPool(permissions.BasePermission):
    """Allows requests authenticated with a worker pool credential."""

    def has_permission(self, request: Request, view: views.APIView) -> bool:
        return isinstance(request.auth, WorkerPool)


class WorkerPoolKeySerializer(serializers.Serializer):
    """Validates the public key a pool registers."""

    public_key = serializers.CharField()

    def validate_public_key(self, value: str) -> str:
        try:
            validate_public_key(value)
        except SealedBoxError as err:
            raise serializers.ValidationError("Invalid public key.") from err

        return value


@extend_schema_view(
    put=extend_schema(description="Set the public key of the worker's pool"),
)
class WorkerPoolKeyView(views.APIView):
    """Lets the workers of a pool register the pool's public key."""

    authentication_classes = [WorkerPoolAuthentication]
    permission_classes = [IsWorkerPool]
    serializer_class = WorkerPoolKeySerializer

    def put(self, request: Request) -> Response:
        """Sets the public key of the authenticated pool and returns 204.

        A pool that already has a key is refused. Replacing a key starts with "Reset key" in the admin, so a credential alone can never replace one.

        Raises:
            WorkerPoolKeyAlreadySetError: if the pool already has a public key.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            pool = WorkerPool.objects.select_for_update().get(pk=request.auth.pk)

            if pool.public_key:
                raise WorkerPoolKeyAlreadySetError()

            pool.public_key = serializer.validated_data["public_key"]
            pool.save(update_fields=["public_key"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(description="Claim the next job of the worker's pool"),
)
class ClaimJobView(views.APIView):
    """Hands the next job of a pool to one of its workers."""

    authentication_classes = [WorkerPoolAuthentication]
    permission_classes = [IsWorkerPool]

    def post(self, request: Request) -> Response:
        """Starts the next job for the worker's QGIS version.

        Returns the job with the command to run and a token that stops working when the job completes, or 204 if there is no job. The token is a secret and must not be logged.
        """
        claimed_job = claim_job(request.auth)

        if not claimed_job:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {
                "job_id": claimed_job.job.pk,
                "job_type": claimed_job.job.type,
                "project_id": claimed_job.job.project_id,
                "token": claimed_job.token,
            }
        )
