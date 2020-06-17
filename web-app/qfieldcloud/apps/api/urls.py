from django.urls import path

from qfieldcloud.apps.api.views import (
    files_views,
    deltas_views,
    status_views,
    members_views,
    collaborators_views,
    projects_views,
    users_views,
)


urlpatterns = [
    path('users/', users_views.ListUsersView.as_view()),
    path('users/<str:username>/',
         users_views.RetrieveUpdateUserView.as_view()),

    path('projects/',
         projects_views.ListProjectsView.as_view()),
    path('projects/<str:owner>/',
         projects_views.ListCreateProjectView.as_view()),
    path('projects/<uuid:projectid>/',
         projects_views.RetrieveUpdateDestroyProjectView.as_view()),

    path('collaborators/<uuid:projectid>/',
         collaborators_views.ListCreateCollaboratorsView.as_view()),
    path('collaborators/<uuid:projectid>/<str:username>/',
         collaborators_views.GetUpdateDestroyCollaboratorView.as_view()),

    path('files/<uuid:projectid>/', files_views.ListFilesView.as_view()),
    path('files/<uuid:projectid>/<path:filename>/',
         files_views.DownloadPushDeleteFileView.as_view()),

    path('members/<str:organization>/',
         members_views.ListCreateMembersView.as_view()),
    path('members/<str:organization>/<str:username>/',
         members_views.GetUpdateDestroyMemberView.as_view()),

    path('status/', status_views.APIStatusView.as_view()),

    path('deltas/<uuid:projectid>/',
         deltas_views.ListCreateDeltaFileView.as_view()),

    path('delta-status/<uuid:deltafileid>/',
         deltas_views.GetDeltaView.as_view()),

]
