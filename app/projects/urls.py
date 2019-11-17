from django.urls import path, re_path

from .views import ProjectView, ProjectFileView, PushView, PullView


urlpatterns = [
    path('', ProjectView.as_view()),
    re_path(r'^(?P<project_name>[^/]+)$', ProjectFileView.as_view()),
    re_path(r'^(?P<project_name>[^/]+)/push$', PushView.as_view()),
    re_path(r'^(?P<project_name>[^/]+)/pull$', PullView.as_view()),
]
