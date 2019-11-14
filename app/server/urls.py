from django.urls import path
from . import views


urlpatterns = [
    path('', views.proba, name='proba')
]
