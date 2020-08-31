from django.urls import path
from .views import IndexView, signup, registered

urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('signup/', signup, name='signup'),
    path('registered/', registered, name='registered'),
]
