from django.conf import settings
from django.core.cache import cache
from qfieldcloud.core import geodb_utils, utils
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


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

            # Cache the result for 10 minutes
            cache.set("status_results", results, 600)

        return Response(results, status=status.HTTP_200_OK)
