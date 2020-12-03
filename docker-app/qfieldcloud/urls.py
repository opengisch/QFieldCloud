'''qfieldcloud URL Configuration

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
'''
from django.contrib import admin
from django.urls import path, re_path, include

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from qfieldcloud.core.views import auth_views

from qfieldcloud.core.web import views as web_views

schema_view = get_schema_view(
    openapi.Info(
        title='QFieldcloud REST API',
        default_version='v1',
        description='Test description',
        terms_of_service='https://',
        contact=openapi.Contact(email='info@opengis.ch'),
        license=openapi.License(name='License'),
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
    path('api/v1/auth/token/', auth_views.AuthTokenView.as_view()),
    path('api/v1/auth/', include('rest_auth.urls')),

    path('api/v1/', include('qfieldcloud.core.urls')),
    path('auth/', include('rest_framework.urls')),

    # Web pages
    path('', web_views.index, name='index'),
    # index is used to get rootUrl in js files. Do NOT change this ^^.

    # public / not logged_in
    # path('public/projects/',
    #      web_views.ProjectFilterListViewPublic.as_view(),
    #      name='home_public'),
    path('accounts/', include('allauth.urls')),

    path('<str:content_owner>/',
         web_views.ProjectFilterListView.as_view(),
         name='home'),
    path('<str:content_owner>/<str:projects>',  # special set of projects
         web_views.ProjectFilterListView.as_view(),
         name='projects_list'),

    path('status/', web_views.status, name='status'),
    path('async_conflicts/<uuid:pk>/',  # TODO only one way
         web_views.async_conflicts,
         name='async_conflicts'),

    # async views
    path('async/my_organizations/',
         web_views.async_my_organizations,
         name='async_my_organizations'),
    path('async/async_possible_collaborators/',  # TODO add project_pk to filter out existing collabs
         web_views.async_possible_collaborators,
         name='async_possible_collaborators'),
    path('async/project/<uuid:proj_pk>/invite_collaborator/<int:user_pk>/',
         web_views.async_invite_project_collaborator,
         name='async_possible_collaborators'),
    path('async/public_projects/',
         web_views.async_public_projects,
         name='async_public_projects'),
    # path('/<uuid:project_pk>/<uuid:collab_pk>/<int:role>',
    #     async_add_project_collaborator,
    #     name='project_delete_confirm'),

    # normal django views
    path('user/profile/<str:content_owner>/<int:pk>/',
         web_views.UserOverview.as_view(),
         name='user_overview'),
    path('<str:content_owner>/settings/<int:pk>/',
         web_views.OrganizationOverview.as_view(),
         name='organization_overview'),
    path('<str:content_owner>/settings/tab=dangerzone/<int:pk>/',
         web_views.OrganizationDangerzone.as_view(),
         name='organization_dangerzone'),
    path('<str:user>/delete/<str:content_owner>/<int:pk>/',
         web_views.OrganizationDeleteView.as_view(),
         name='organization_confirm_delete'),

    path('create_organization_for/<str:content_owner>/',
         web_views.OrganizationCreate.as_view(),
         name='organization_create'),

    path('<str:content_owner>/<str:project>/tab=collaborators/<uuid:pk>/',
         web_views.ProjectCollaboratorFilterListView.as_view(),
         name='project_collaborators'),
    path('<str:content_owner>/<str:project>/<uuid:pk>/',
         web_views.ProjectOverview.as_view(),
         name='project_overview'),
    path('<str:content_owner>/<str:project>/tab=conflicts/<uuid:pk>/',
         web_views.conflicts,
         name='project_conflicts'),
    path('<str:content_owner>/<str:project>/tab=dangerzone/<uuid:pk>/',
         web_views.ProjectDangerzone.as_view(),
         name='project_dangerzone'),
    path('<str:content_owner>/<str:project>/delete/<uuid:pk>/',
         web_views.ProjectDeleteView.as_view(),
         name='project_confirm_delete'),

    path('create_project_for/<str:content_owner>/',
         web_views.ProjectCreateView.as_view(),
         name='project_create'),

    path('user_language/<str:lang>/',
         web_views.user_language,
         name='user_language'),

]
