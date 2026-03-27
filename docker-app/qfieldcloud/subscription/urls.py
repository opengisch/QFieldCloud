from django.urls import path

from qfieldcloud.subscription.views import RetrieveCurrentSubscriptionView

urlpatterns = [
    path(
        "subscriptions/<str:username>/current/",
        RetrieveCurrentSubscriptionView.as_view(),
        name="retrieve_current_subscription",
    ),
]
