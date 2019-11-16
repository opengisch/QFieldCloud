from django.urls import path, re_path

from .views import ProjectList, ProjectDetail, FileUploadView


urlpatterns = [
    path('<int:pk>/', ProjectDetail.as_view()),
    re_path(r'^upload/(?P<filename>[^/]+)$', FileUploadView.as_view()),
    path('', ProjectList.as_view()),
]
