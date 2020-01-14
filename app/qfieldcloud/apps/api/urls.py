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
)


urlpatterns = [
    path('users/', ListUsersView.as_view()),
    path('users/<str:name>/', RetrieveUserView.as_view()),
    path('users/user/', RetrieveUpdateAuthenticatedUserView.as_view()),

    path('projects/', ListProjectsView.as_view()),
    path('projects/user/', ListUserProjectsView.as_view()),
    path('projects/<str:owner>/', ListCreateProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/',
         RetrieveUpdateDestroyProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/push/', PushFileView.as_view()),
    path('projects/<str:owner>/<str:project>/files/', ListFilesView.as_view()),
    path('projects/<str:owner>/<str:project>/collaborators/',
         ListCollaboratorsView.as_view()),
    path('projects/<str:owner>/<str:project>/collaborators/<str:username>/',
         CheckCreateDestroyCollaboratorView.as_view()),
    path('projects/<str:owner>/<str:project>/<str:filename>/',
         RetrieveDestroyFileView.as_view()),
]
