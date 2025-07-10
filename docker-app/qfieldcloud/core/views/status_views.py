from django.core.cache import cache
from django.core.files.storage import storages
from django.db import connections
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.core import geodb_utils
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema_view(
    get=extend_schema(description="Get the current status of the API"),
)
class APIStatusView(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        # Try to get the status from the cache
        results = cache.get("status_results", {})
        if not results:
            # check geodb
            results["geodb"] = "ok"
            if not geodb_utils.geodb_is_running():
                results["geodb"] = "error"

            # check database
            results["database"] = "ok"
            db_conn = connections["default"]
            try:
                with db_conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except OperationalError:
                results["database"] = "error"

            # check storages
            results["storages"] = {}
            for storage_key in storages.backends.keys():
                storage = storages[storage_key]

                try:
                    results["storages"][storage_key] = storage.check_status()
                except Exception:
                    # ManifestStaticFilesStorage may not have check_status method.
                    continue

            # Cache the result for 10 minutes
            cache.set("status_results", results, 600)

        return Response(results, status=status.HTTP_200_OK)
