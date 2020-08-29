from django.urls import path, include

from qfieldcloud.apps.api.views import (
    files_views,
    deltas_views,
    status_views,
    members_views,
    collaborators_views,
    projects_views,
    users_views,
    qfield_files_views,
)

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'projects', projects_views.ProjectViewSet, basename='project')

urlpatterns = [
    path('users/', users_views.ListUsersView.as_view()),
    path('users/<str:username>/',
         users_views.RetrieveUpdateUserView.as_view()),

    path('', include(router.urls)),

    path('collaborators/<uuid:projectid>/',
         collaborators_views.ListCreateCollaboratorsView.as_view()),
    path('collaborators/<uuid:projectid>/<str:username>/',
         collaborators_views.GetUpdateDestroyCollaboratorView.as_view()),

    path('files/<uuid:projectid>/', files_views.ListFilesView.as_view()),
    path('files/<uuid:projectid>/<path:filename>/',
         files_views.DownloadPushDeleteFileView.as_view()),

    path('qfield-files/<uuid:projectid>/',
         qfield_files_views.ExportView.as_view()),
    path('qfield-files/export/<uuid:jobid>/',
         qfield_files_views.ListFilesView.as_view()),
    path('qfield-files/export/<uuid:jobid>/<path:filename>/',
         qfield_files_views.DownloadFileView.as_view()),

    path('members/<str:organization>/',
         members_views.ListCreateMembersView.as_view()),
    path('members/<str:organization>/<str:username>/',
         members_views.GetUpdateDestroyMemberView.as_view()),

    path('status/', status_views.APIStatusView.as_view()),

    path('deltas/<uuid:projectid>/',
         deltas_views.ListCreateDeltaFileView.as_view()),

    path('deltas/status/<uuid:jobid>/',
         deltas_views.GetDeltaView.as_view()),

]
