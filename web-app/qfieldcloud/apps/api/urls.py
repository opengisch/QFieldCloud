from django.urls import path

from .views import (
    RetrieveUserView,
    ListUsersView,
    RetrieveUpdateAuthenticatedUserView,
    ListProjectsView,
    ListUserProjectsView,
    ListCreateProjectView,
    RetrieveUpdateDestroyProjectView,
    ListFilesView,
    CreateRetrieveDestroyFileView,
    ListCollaboratorsView,
    CheckCreateDestroyCollaboratorView,
)


urlpatterns = [
    path('users/user/', RetrieveUpdateAuthenticatedUserView.as_view()),
    path('users/', ListUsersView.as_view()),
    path('users/<str:username>/', RetrieveUserView.as_view()),

    path('projects/user/', ListUserProjectsView.as_view()),
    path('projects/', ListProjectsView.as_view()),
    path('projects/<str:owner>/', ListCreateProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/',
         RetrieveUpdateDestroyProjectView.as_view()),

    path('collaborators/<str:owner>/<str:project>/',
         ListCollaboratorsView.as_view()),
    path('collaborators/<str:owner>/<str:project>/<str:username>/',
         CheckCreateDestroyCollaboratorView.as_view()),

    path('files/<str:owner>/<str:project>/', ListFilesView.as_view()),
    path('files/<str:owner>/<str:project>/<path:filename>/',
         CreateRetrieveDestroyFileView.as_view()),
]
