from django.urls import path, re_path

from .views import RepositoryList, RepositoryDetail, FileUploadView


urlpatterns = [
    path('<int:pk>/', RepositoryDetail.as_view()),
    re_path(r'^upload/(?P<filename>[^/]+)$', FileUploadView.as_view()),
    path('', RepositoryList.as_view()),
]
