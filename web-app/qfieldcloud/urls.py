"""qfieldcloud URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path, include

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


schema_view = get_schema_view(
   openapi.Info(
      title="QFieldcloud REST API",
      default_version='v1',
      description="Test description",
      terms_of_service="https://",
      contact=openapi.Contact(email="info@opengis.ch"),
      license=openapi.License(name="License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

urlpatterns = [

    re_path(r'^swagger(?P<format>\.json|\.yaml)$',
            schema_view.without_ui(cache_timeout=0),
            name='schema-json'),
    path('swagger/',
         schema_view.with_ui('swagger', cache_timeout=0),
         name='schema-swagger-ui'),
    path('docs/',
         schema_view.with_ui('redoc', cache_timeout=0),
         name='schema-redoc'),

    path('admin/', admin.site.urls),
    path('api/v1/auth/registration/', include('rest_auth.registration.urls')),
    path('api/v1/auth/', include('rest_auth.urls')),
    path('api/v1/', include('qfieldcloud.apps.api.urls')),
    path('auth/', include('rest_framework.urls')),
]
