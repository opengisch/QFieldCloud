import time

from django.conf import settings
from django.core.cache import cache
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from qfieldcloud.core import exceptions, geodb_utils, utils
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@method_decorator(
    name="get",
    decorator=swagger_auto_schema(
        operation_description="Get the current status of the APIs",
        operation_id="Get status",
    ),
)
class APIStatusView(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request):

        # Try to get the status from the cache
        results = cache.get("status_results", {})
        if not results:

            results["redis"] = "ok"
            # Check if redis is visible
            if not utils.redis_is_running():
                results["redis"] = "error"

            results["geodb"] = "ok"
            # Check geodb
            if not geodb_utils.geodb_is_running():
                results["geodb"] = "error"

            results["storage"] = "ok"
            # Check if bucket exists (i.e. the connection works)
            try:
                s3_client = utils.get_s3_client()
                s3_client.head_bucket(Bucket=settings.STORAGE_BUCKET_NAME)
            except Exception:
                results["storage"] = "error"

            job = utils.check_orchestrator_status()
            results["orchestrator"] = "ok"
            # Wait for the worker to finish
            for _ in range(30):
                time.sleep(2)
                if job.get_status() == "finished":
                    if _ >= 10:
                        results["orchestrator"] = "slow"
                    else:
                        results["orchestrator"] = "ok"
                    break
                if job.get_status() == "failed":
                    break

            if not job.get_status() in ["finished"]:
                results["orchestrator"] = "error"

            # Cache the result for 10 minutes
            cache.set("status_results", results, 600)

        for result in results:
            if not results[result] in ["slow", "ok"]:
                raise exceptions.StatusNotOkError(message=result)

        return Response(results, status=status.HTTP_200_OK)
