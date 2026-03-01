from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.templatetags.static import static
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import extend_schema, extend_schema_view
from qfieldcloud.core.whitelabel import get_whitelabel_settings
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

User = get_user_model()


@extend_schema_view(
    get=extend_schema(description="Get the current status of the API"),
)
class ServerInfoView(views.APIView):
    permission_classes = [AllowAny]

    @method_decorator(cache_page(60))
    def get(self, request: HttpRequest) -> Response:
        whitelabel_settings = get_whitelabel_settings()

        # the whitelabel settings contain paths to static files, we need to convert them to absolute URLs
        for key in ["logo_navbar", "logo_main", "favicon"]:
            whitelabel_settings[key] = request.build_absolute_uri(
                static(whitelabel_settings[key])
            )

        results = {
            "whitelabel": {
                **whitelabel_settings,
            }
        }

        return Response(results, status=status.HTTP_200_OK)
