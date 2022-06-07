"""qfieldcloud URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path(
        '', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path(
        '', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path(
        'blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.utils.translation import gettext as _
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from qfieldcloud.authentication import views as auth_views
from qfieldcloud.core.views import files_views
from rest_framework import permissions

admin.site.site_header = _("QFieldCloud Admin")
admin.site.site_title = _("QFieldCloud Admin")
admin.site.index_title = _("Welcome to QFieldCloud Admin")

schema_view = get_schema_view(
    openapi.Info(
        title="QFieldcloud REST API",
        default_version="v1",
        description="Test description",
        terms_of_service="https://",
        contact=openapi.Contact(email="info@opengis.ch"),
        license=openapi.License(name="License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path(
        settings.QFIELDCLOUD_ADMIN_URI + "api/files/<uuid:projectid>/",
        files_views.ListFilesView.as_view(permission_classes=[permissions.IsAdminUser]),
    ),
    path(
        settings.QFIELDCLOUD_ADMIN_URI + "api/files/<uuid:projectid>/<path:filename>/",
        files_views.DownloadPushDeleteFileView.as_view(
            permission_classes=[permissions.IsAdminUser]
        ),
        name="project_file_download",
    ),
    path(settings.QFIELDCLOUD_ADMIN_URI, admin.site.urls),
    path("docs/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    path("api/v1/auth/login/", auth_views.LoginView.as_view()),
    path("api/v1/auth/token/", auth_views.LoginView.as_view()),
    path("api/v1/auth/user/", auth_views.UserView.as_view()),
    path("api/v1/auth/logout/", auth_views.LogoutView.as_view()),
    path("api/v1/", include("qfieldcloud.core.urls")),
    path("auth/", include("rest_framework.urls")),
    path("accounts/", include("allauth.urls")),
    re_path(r"^invitations/", include("invitations.urls", namespace="invitations")),
    path("__debug__/", include("debug_toolbar.urls")),
]
