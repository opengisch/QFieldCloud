from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import User
from qfieldcloud.subscription.models import Subscription
from qfieldcloud.subscription.serializers import CurrentSubscriptionSerializer


class RetrieveCurrentSubscriptionViewPermissions(BasePermission):
    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        user_for_account: User = obj.account.user

        return permissions_utils.can_read_current_subscription(
            request.user,
            user_for_account,
        )


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
