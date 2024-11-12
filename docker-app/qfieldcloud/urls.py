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
from django.urls import include, path
from django.utils.translation import gettext as _
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from qfieldcloud.authentication import views as auth_views
from qfieldcloud.core.views import files_views
from rest_framework import permissions

admin.site.site_header = _("QFieldCloud Admin")
admin.site.site_title = _("QFieldCloud Admin")
admin.site.index_title = _("Welcome to QFieldCloud Admin")


urlpatterns = [
    path(
        "",
        RedirectView.as_view(url=settings.QFIELDCLOUD_ADMIN_URI, permanent=False),
        name="index",
    ),
    path(
        "swagger.yaml",
        SpectacularAPIView.as_view(),
        name="openapi_schema",
    ),
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(url_name="openapi_schema"),
        name="openapi_swaggerui",
    ),
    path(
        "docs/",
        SpectacularRedocView.as_view(url_name="openapi_schema"),
        name="openapi_redoc",
    ),
    path(
        settings.QFIELDCLOUD_ADMIN_URI + "api/files/<uuid:projectid>/",
        files_views.AdminListFilesViews.as_view(
            permission_classes=[permissions.IsAdminUser]
        ),
    ),
    path(
        settings.QFIELDCLOUD_ADMIN_URI + "api/files/<uuid:projectid>/<path:filename>/",
        files_views.AdminDownloadPushDeleteFileView.as_view(
            permission_classes=[permissions.IsAdminUser]
        ),
        name="project_file_download",
    ),
    path(settings.QFIELDCLOUD_ADMIN_URI, admin.site.urls),
    path("api/v1/auth/login/", auth_views.LoginView.as_view()),
    path("api/v1/auth/token/", auth_views.LoginView.as_view()),
    path("api/v1/auth/user/", auth_views.UserView.as_view()),
    path("api/v1/auth/logout/", auth_views.LogoutView.as_view()),
    path("api/v1/", include("qfieldcloud.core.urls")),
    path("auth/", include("rest_framework.urls")),
    path("accounts/", include("allauth.urls")),
    path("invitations/", include("invitations.urls", namespace="invitations")),
    path("__debug__/", include("debug_toolbar.urls")),
]
