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
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
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
