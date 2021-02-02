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

from qfieldcloud.core.web.views import (async_json_views,
                                        projects_views,
                                        users_views,
                                        collaborators_views,
                                        members_views,
                                        pages_views)

from qfieldcloud.core.web.views.permissions_mixins import (PermissionsContextMixin,
                                                           ProjectPermissionsContextMixin)

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

    path('accounts/', include('allauth.urls')),
    re_path(r'^invitations/',
            include('invitations.urls', namespace='invitations')),

    path('', pages_views.index, name='index'),
    path('<str:unpermitted_action>/unpermitted',
         pages_views.unpermitted, name='unpermitted'),

    # The string variables are the parameters used
    # to derive permissions of the user that makes the request.
    path('async/my_organizations/',
         async_json_views.async_my_organizations,
         name='async_my_organizations'),
    path(f'async/possible_collaborators_for_project/{ProjectPermissionsContextMixin.url_project_pk}/',
         async_json_views.async_possible_collaborators,
         name='async_possible_collaborators'),
    path(f'async/possible_members_for_organization/{PermissionsContextMixin.url_content_owner}/',
         async_json_views.async_possible_members,
         name='async_possible_members'),
    path('async/public_projects/',
         async_json_views.async_public_projects,
         name='async_public_projects'),
    # path('async/project/{ProjectPermissionsContextMixin.url_project_pk}/create_collaborator/<str:username>/',
    # maybe need js once using inviation emails
    #      async_json_views.async_create_collaborator,
    #      name='async_create_collaborator'),


    path('projects/create/',
        projects_views.ProjectCreateView.as_view(),
        name='project_create'
    ),

    path('organizations/create/',
        projects_views.ProjectOverviewView.as_view(),
        name='organization_create'
    ),

    path('<str:username>/',
        projects_views.ProjectFilterListView.as_view(),
        name='profile_overview'
    ),
    path('<str:username>/<str:project>/',
        projects_views.ProjectOverviewView.as_view(),
        name='project_overview'
    ),
    path('<str:username>/<str:project>/files',
        projects_views.ProjectFilesView.as_view(),
        name='project_files'
    ),
    path('<str:username>/<str:project>/changes',
        projects_views.ProjectChangesListView.as_view(),
        name='project_changes'
    ),
    path('<str:username>/<str:project>/collaborators',
        projects_views.ProjectCollaboratorsView.as_view(),
        name='project_collaborators'
    ),
    path('<str:username>/<str:project>/collaborators/invite',
        projects_views.ProjectCollaboratorsInviteView.as_view(),
        name='project_collaborators_invite'
    ),
    path('<str:username>/<str:project>/yolo',
        projects_views.ProjectYoloView.as_view(),
        name='project_yolo'
    ),

#     path(*(lambda v: [f'{v.url_content_owner}/',
#                       v.as_view()])(projects_views.ProjectFilterListView),
#          name='home'),
#     # path('public/projects/',
#     #      projects_views.ProjectFilterListViewPublic.as_view(),
#     #      name='home_public'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project_preferences>/projects',
#                       v.as_view()])(projects_views.ProjectFilterListView),
#          # special set of projects
#          name='projects_list'),

#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/<uuid:pk>/',
#                       v.as_view()])(projects_views.ProjectOverview),
#          name='project_overview'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/<uuid:pk>/<str:files>/',
#                       v.as_view()])(projects_views.ProjectFilterListView),
#          name='project_files'),
#     path(*(lambda v: [f'create_project_for/{v.url_content_owner}/',
#                       v.as_view()])(projects_views.ProjectCreateView),
#          name='project_create'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=dangerzone/<uuid:pk>/',
#                       v.as_view()])(projects_views.ProjectDangerzone),
#          name='project_dangerzone'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/delete/<uuid:pk>/',
#                       v.as_view()])(projects_views.ProjectDeleteView),
#          name='project_confirm_delete'),

#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=collaborators/{v.url_project_pk}/',
#                       v.as_view()])(collaborators_views.CollaboratorsOfProjectFilterListView),
#          name='project_collaborators'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=collaborators/<str:collaborator>/<int:pk>/{v.url_project_pk}/',
#                       v.as_view()])(collaborators_views.CollaboratorUpdateView),
#          name='collaborator_details'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=collaborators/create/<str:candidate>/{v.url_project_pk}/',
#                       v.as_view()])(collaborators_views.CollaboratorCreateView),
#          name='collaborator_create'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=collaborators/delete/<str:collaborator>/<int:pk>/{v.url_project_pk}/',
#                       v.as_view()])(collaborators_views.CollaboratorDeleteView),
#          name='collaborator_confirm_delete'),

#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=deltas/{v.url_project_pk}/',
#                       v.as_view()])(deltas_views.DeltasOfProjectFilterListView),
#          name='project_deltas'),
#     path(*(lambda v: [f'{v.url_content_owner}/<str:project>/tab=deltas/<str:deltafile_id>/<uuid:pk>/{v.url_project_pk}/',
#                       v.as_view()])(deltas_views.DeltaDetailView),
#          name='delta_details'),

#     path(*(lambda v: [f'user/profile/{v.url_content_owner}/<int:pk>/',
#                       v.as_view()])(users_views.UserOverview),
#          name='user_overview'),

#     path(*(lambda v: [f'{v.url_content_owner}/settings/<int:pk>/',
#                       v.as_view()])(users_views.OrganizationOverview),
#          name='organization_overview'),
#     path(*(lambda v: [f'{v.url_content_owner}/create_organization/',
#                       v.as_view()])(users_views.OrganizationCreate),
#          name='organization_create'),
#     path(*(lambda v: [f'{v.url_content_owner}/settings/tab=dangerzone/<int:pk>/',
#                       v.as_view()])(users_views.OrganizationDangerzone),
#          name='organization_dangerzone'),
#     path(*(lambda v: [f'<str:user>/delete/{v.url_content_owner}/<int:pk>/',
#                       v.as_view()])(users_views.OrganizationDeleteView),
#          name='organization_confirm_delete'),
#     path(*(lambda v: [f'{v.url_content_owner}/settings/tab=members/',
#                       v.as_view()])(members_views.MembersOfOrganizationFilterListView),
#          name='organization_members'),
#     path(*(lambda v: [f'{v.url_content_owner}/settings/tab=members/<str:member>/<int:pk>/',
#                       v.as_view()])(members_views.MemberUpdateView),
#          name='member_details'),
#     path(*(lambda v: [f'{v.url_content_owner}/settings/tab=members/create/<str:candidate>/',
#                       v.as_view()])(members_views.MemberCreateView),
#          name='member_create'),
#     path(*(lambda v: [f'{v.url_content_owner}/settings/tab=members/delete/<str:member>/<int:pk>/',
#                       v.as_view()])(members_views.MemberDeleteView),
#          name='member_confirm_delete'),

    # path('user_language/<str:lang>/',
    #      users_views.user_language,
    #      name='user_language'),
]
