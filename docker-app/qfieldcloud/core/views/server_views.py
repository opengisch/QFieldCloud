from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.core.serializers import ServerInfoSerializer
from qfieldcloud.core.whitelabel import get_whitelabel_settings
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response


@extend_schema_view(
    get=extend_schema(description="Get server information"),
)
class ServerInfoView(views.APIView):
    permission_classes = [AllowAny]
    serializer_class = ServerInfoSerializer

    @method_decorator(cache_page(60))
    def get(self, request: Request) -> Response:
        results = self.serializer_class(
            {
                "whitelabel": get_whitelabel_settings(),
            },
            context={"request": request},
        )

        return Response(results.data, status=status.HTTP_200_OK)
