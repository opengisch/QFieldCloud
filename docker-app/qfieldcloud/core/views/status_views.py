from django.core.cache import cache
from django.core.files.storage import storages
from django.db import connections
from drf_spectacular.utils import extend_schema, extend_schema_view
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
            # check database
            results["database"] = "ok"
            db_conn = connections["default"]
            try:
                with db_conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except Exception:
                results["database"] = "error"

            # check storages
            results["storage"] = "ok"
            for storage_key in storages.backends.keys():
                storage = storages[storage_key]

                if not hasattr(storage, "check_status"):
                    # Some storages may not have the check_status method.
                    # e.g. ManifestStaticFilesStorage.
                    continue

                try:
                    if not storage.check_status():
                        results["storage"] = "error"
                        break
                except Exception:
                    results["storage"] = "error"
                    break

            # Cache the result for 10 minutes
            cache.set("status_results", results, 600)

        return Response(results, status=status.HTTP_200_OK)
