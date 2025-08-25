import logging
from enum import Enum
from typing import TypedDict

from constance import config
from django.core.files.storage import storages
from django.db import connections
from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class StatusValue(str, Enum):
    OK = "ok"
    ERROR = "error"


class StatusDict(TypedDict):
    database: StatusValue
    storage: StatusValue
    status_page_url: str | None
    incident_message: str | None
    incident_timestamp_utc: str | None


@extend_schema_view(
    get=extend_schema(description="Get the current status of the API"),
)
class APIStatusView(views.APIView):
    permission_classes = [AllowAny]

    @method_decorator(cache_page(60))
    def get(self, _request: HttpRequest) -> Response:
        results: StatusDict = {
            "database": self._check_db(),
            "storage": self._check_storages(),
            "status_page_url": None,
            "incident_message": None,
            "incident_timestamp_utc": None,
        }

        # add status page url if set
        if config.STATUS_PAGE_URL:
            results["status_page_url"] = config.STATUS_PAGE_URL

        # add info about ongoing incident if any
        if config.INCIDENT_IS_ACTIVE:
            logger.warning(
                "Incident is active, reporting incident details in status API since %s with message: %s",
                config.INCIDENT_TIMESTAMP_UTC,
                config.INCIDENT_MESSAGE,
            )

            results["incident_message"] = config.INCIDENT_MESSAGE
            results["incident_timestamp_utc"] = config.INCIDENT_TIMESTAMP_UTC

        return Response(results, status=status.HTTP_200_OK)

    def _check_db(self) -> StatusValue:
        try:
            db_conn = connections.create_connection("default")

            with db_conn.cursor() as cursor:
                cursor.execute("SELECT 1")

            return StatusValue.OK
        except Exception:
            logger.error('Failed to connect to the database "default".', exc_info=True)

            # just to be safe, we catch all exceptions and set the status to error again.
            return StatusValue.ERROR

    def _check_storages(self) -> StatusValue:
        checked_storage_count = 0

        # check all storages are reachable
        for storage_key in storages.backends.keys():
            storage = storages[storage_key]

            if not hasattr(storage, "check_status"):
                # Some storages may not have the check_status method.
                # e.g. ManifestStaticFilesStorage.
                continue

            checked_storage_count += 1

            try:
                if not storage.check_status():
                    logger.error(f"Storage '{storage_key}' is not reachable.")

                    # no need to check other storages if one already failed
                    return StatusValue.ERROR
            except Exception:
                logger.error(
                    f"Storage '{storage_key}' raised an error while checking status.",
                    exc_info=True,
                )

                return StatusValue.ERROR

        if checked_storage_count == 0:
            # If no storage was checked, we consider it an error.
            return StatusValue.ERROR

        return StatusValue.OK
