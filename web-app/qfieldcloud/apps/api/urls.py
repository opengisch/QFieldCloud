from django.urls import path

from .views import (
    ListUsersView,
    RetrieveUpdateUserView,
    ListProjectsView,
    ListCreateProjectView,
    RetrieveUpdateDestroyProjectView,
    ListFilesView,
    CreateRetrieveDestroyFileView,
    ListCreateCollaboratorsView,
    GetUpdateDestroyCollaboratorView,
    ListCreateMembersView,
    GetUpdateDestroyMemberView,
)


urlpatterns = [
    path('users/', ListUsersView.as_view()),
    path('users/<str:username>/',
         RetrieveUpdateUserView.as_view()),

    path('projects/', ListProjectsView.as_view()),
    path('projects/<str:owner>/', ListCreateProjectView.as_view()),
    path('projects/<str:owner>/<str:project>/',
         RetrieveUpdateDestroyProjectView.as_view()),

    path('collaborators/<str:owner>/<str:project>/',
         ListCreateCollaboratorsView.as_view()),
    path('collaborators/<str:owner>/<str:project>/<str:username>/',
         GetUpdateDestroyCollaboratorView.as_view()),

    path('files/<str:owner>/<str:project>/', ListFilesView.as_view()),
    path('files/<str:owner>/<str:project>/<path:filename>/',
         CreateRetrieveDestroyFileView.as_view()),

    path('members/<str:organization>/',
         ListCreateMembersView.as_view()),
    path('members/<str:organization>/<str:username>/',
         GetUpdateDestroyMemberView.as_view()),
]
