from django.urls import path

from .views import (
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
    path('', ListProjectsView.as_view()),
    path('user/', ListUserProjectsView.as_view()),
    path('<str:owner>/', ListCreateProjectView.as_view()),
    path('<str:owner>/<str:project>/',
         RetrieveUpdateDestroyProjectView.as_view()),
    path('<str:owner>/<str:project>/push/', PushFileView.as_view()),
    path('<str:owner>/<str:project>/files/', ListFilesView.as_view()),
    path('<str:owner>/<str:project>/collaborators/',
         ListCollaboratorsView.as_view()),
    path('<str:owner>/<str:project>/collaborators/<str:username>/',
         CheckCreateDestroyCollaboratorView.as_view()),
    path('<str:owner>/<str:project>/<str:filename>/',
         RetrieveDestroyFileView.as_view()),
]
