from django.urls import path

from .views import (
    RetrieveUserView,
    ListUsersView,
    RetrieveUpdateAuthenticatedUserView,
)


urlpatterns = [
    path('', ListUsersView.as_view()),
    path('<str:name>/', RetrieveUserView.as_view()),
    path('user/', RetrieveUpdateAuthenticatedUserView.as_view()),
]
