from django.utils.decorators import method_decorator

from rest_framework import views, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from drf_yasg.utils import swagger_auto_schema

from qfieldcloud.apps.api import qgis_utils


@method_decorator(
    name='get', decorator=swagger_auto_schema(
        operation_description="Get the current status of the APIs",
        operation_id="Get status",))
class APIStatusView(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request):

        if not qgis_utils.orchestrator_is_running():
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE,
                            data="The orchestator is not running!")

        return Response(status=status.HTTP_200_OK)
