from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.authentication.authentication import (
    TokenAuthentication,
    WorkerPoolAuthentication,
)
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.exceptions import WorkerPoolKeyAlreadySetError
from qfieldcloud.core.job_results import get_job_command
from qfieldcloud.core.models import WorkerPool
from qfieldcloud.core.sealed_box import SealedBoxError, validate_public_key
from qfieldcloud.core.worker_pools import (
    DEFAULT_QGIS_MAJOR_VERSION,
    JOB_REPORT_TIMEOUT,
    claim_job,
    complete_job,
    fetch_job_deltafile,
    fetch_job_secrets,
)
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


class ClaimJobSerializer(serializers.Serializer):
    """Validates the QGIS major version a worker runs."""

    qgis_major_version = serializers.IntegerField(default=DEFAULT_QGIS_MAJOR_VERSION)


@extend_schema_view(
    post=extend_schema(description="Claim the next job of the worker's pool"),
)
class ClaimJobView(views.APIView):
    """Hands the next job of a pool to one of its workers."""

    authentication_classes = [WorkerPoolAuthentication]
    permission_classes = [IsWorkerPool]

    serializer_class = ClaimJobSerializer

    def post(self, request: Request) -> Response:
        """Starts the next job for the worker's QGIS version.

        Returns the job with the command to run and a token that stops working when the job completes, or 204 if there is no job. The token is a secret and must not be logged.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        claimed_job = claim_job(
            request.auth, serializer.validated_data["qgis_major_version"]
        )

        if not claimed_job:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(
            {
                "job_id": claimed_job.job.pk,
                "job_type": claimed_job.job.type,
                "project_id": claimed_job.job.project_id,
                "command": get_job_command(claimed_job.job),
                "timeout_s": settings.QFIELDCLOUD_WORKER_TIMEOUT_S,
                "report_timeout_s": int(JOB_REPORT_TIMEOUT.total_seconds()),
                "token": claimed_job.token,
            }
        )


@extend_schema_view(
    post=extend_schema(description="Fetch the sealed secrets of a job, once"),
)
class FetchJobSecretsView(views.APIView):
    """Gives a worker the sealed secrets of its job."""

    authentication_classes = [WorkerPoolAuthentication]
    permission_classes = [IsWorkerPool]

    def post(self, request: Request, job_id: str) -> Response:
        """Returns the sealed secrets of a running job of the pool. Works once per job.

        A job with secrets its pool cannot read is failed, so it never runs without them.
        """
        sealed_values = fetch_job_secrets(job_id, request.auth)

        return Response(
            {
                "secrets": [
                    {
                        "secret_id": sealed_value.secret.pk,
                        "ciphertext": sealed_value.ciphertext,
                    }
                    for sealed_value in sealed_values
                ]
            }
        )


class IsWorkerToken(permissions.BasePermission):
    """Allows requests authenticated with the short lived token of a job."""

    def has_permission(self, request: Request, view: views.APIView) -> bool:
        return (
            isinstance(request.auth, AuthToken)
            and request.auth.client_type == AuthToken.ClientType.WORKER
        )


class CompleteJobSerializer(serializers.Serializer):
    """Validates the result a job runner reports."""

    exit_code = serializers.IntegerField()
    # NOTE explicit, as the exit code of a stopped job cannot be told apart from one the job chose
    timed_out = serializers.BooleanField(default=False)
    # NOTE files, because they may be far larger than Django accepts for other request data
    feedback = serializers.FileField(required=False, allow_empty_file=True)
    output = serializers.FileField(required=False, allow_empty_file=True)


@extend_schema_view(
    post=extend_schema(description="Report the result of a job"),
)
class CompleteJobView(views.APIView):
    """Receives the result of a job from its runner."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsWorkerToken]
    serializer_class = CompleteJobSerializer

    def post(self, request: Request, job_id: str) -> Response:
        """Finishes or fails a running job of the token's user and returns 204.

        The token stops working afterwards. The results come from a worker that may run outside of our control, so they are validated before being applied.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        complete_job(
            job_id,
            request.auth,
            serializer.validated_data["exit_code"],
            serializer.validated_data["timed_out"],
            serializer.validated_data.get("feedback"),
            serializer.validated_data.get("output"),
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    post=extend_schema(description="Fetch the deltafile of a delta job, once"),
)
class FetchJobDeltafileView(views.APIView):
    """Gives a worker the deltas of its job."""

    authentication_classes = [WorkerPoolAuthentication]
    permission_classes = [IsWorkerPool]

    def post(self, request: Request, job_id: str) -> Response:
        """Returns the deltafile of a running delta job of the pool and marks its deltas as started. Works once per job."""
        return Response(fetch_job_deltafile(job_id, request.auth))
