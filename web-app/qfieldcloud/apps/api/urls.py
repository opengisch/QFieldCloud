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
    APIStatusView,
)


urlpatterns = [
    path('users/', ListUsersView.as_view()),
    path('users/<str:username>/',
         RetrieveUpdateUserView.as_view()),

    path('projects/', ListProjectsView.as_view()),
    path('projects/<str:owner>/', ListCreateProjectView.as_view()),
    path('projects/<uuid:projectid>/',
         RetrieveUpdateDestroyProjectView.as_view()),

    path('collaborators/<uuid:projectid>/',
         ListCreateCollaboratorsView.as_view()),
    path('collaborators/<uuid:projectid>/<str:username>/',
         GetUpdateDestroyCollaboratorView.as_view()),

    path('files/<uuid:projectid>/', ListFilesView.as_view()),
    path('files/<uuid:projectid>/<path:filename>/',
         CreateRetrieveDestroyFileView.as_view()),

    path('members/<str:organization>/',
         ListCreateMembersView.as_view()),
    path('members/<str:organization>/<str:username>/',
         GetUpdateDestroyMemberView.as_view()),

    path('status/', APIStatusView.as_view()),
]
