from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated

from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import User
from qfieldcloud.subscription.models import Subscription
from qfieldcloud.subscription.serializers import CurrentSubscriptionSerializer


class RetrieveCurrentSubscriptionViewPermissions(BasePermission):
    def has_permission(self, request, view):
        username = permissions_utils.get_param_from_request(request, "username")

        try:
            user = User.objects.get(username=username)
        except ObjectDoesNotExist:
            return False

        return permissions_utils.can_read_current_subscription(request.user, user)


@extend_schema_view(
    get=extend_schema(
        description="Retrieve the current subscription for a user or organization",
    ),
)
class RetrieveCurrentSubscriptionView(RetrieveAPIView):
    """Retrieve the current subscription for a user or organization."""

    permission_classes = [
        IsAuthenticated,
        RetrieveCurrentSubscriptionViewPermissions,
    ]
    serializer_class = CurrentSubscriptionSerializer

    def get_object(self) -> Subscription:
        user = User.objects.select_related("useraccount").get(
            username=self.kwargs["username"]
        )

        return user.useraccount.current_subscription
