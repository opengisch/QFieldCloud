from django.urls import path

from .views import ProjectList, ProjectDetail


urlpatterns = [
    path('<int:pk>/', ProjectDetail.as_view()),
    path('', ProjectList.as_view()),
]
