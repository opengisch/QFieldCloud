from django.urls import path

from .views import (
    RetrieveUserView,
    ListUsersView,
    RetrieveUpdateAuthenticatedUserView,
    ListProjectsView,
    ListUserProjectsView,
    ListCreateProjectView,
    RetrieveUpdateDestroyProjectView,
    PushFileView,
    ListFilesView,
    RetrieveDestroyFileView,
    ListCollaboratorsView,
    CheckCreateDestroyCollaboratorView,
    HistoryView,
)


urlpatterns = [
    path('users/user/', RetrieveUpdateAuthenticatedUserView.as_view()),
    path('users/', ListUsersView.as_view()),
    path('users/<str:username>/', RetrieveUserView.as_view()),

    path('projects/user/', ListUserProjectsView.as_view()),
    path('projects/', ListProjectsView.as_view()),
    path('projects/<str:owner>/', ListCreateProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/push/', PushFileView.as_view()),
    path('projects/<str:owner>/<str:project>/files/', ListFilesView.as_view()),
    path('projects/<str:owner>/<str:project>/collaborators/',
         ListCollaboratorsView.as_view()),
    path('projects/<str:owner>/<str:project>/collaborators/<str:username>/',
         CheckCreateDestroyCollaboratorView.as_view()),
    path('projects/<str:owner>/<str:project>/',
         RetrieveUpdateDestroyProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/<path:filename>/',
         RetrieveDestroyFileView.as_view()),

    # TODO: choose a better name?
    path('history/<str:owner>/<str:project>/<path:filename>/',
         HistoryView.as_view()),
]
