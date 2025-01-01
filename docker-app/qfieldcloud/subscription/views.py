from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from qfieldcloud.subscription.serializers import CurrentSubscriptionSerializer


class CurrentSubscriptionView(RetrieveAPIView):
    """Read current subscription information including storage details.

    Accepts nothing, returns the current subscription information.
    """

    serializer_class = CurrentSubscriptionSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user.useraccount.current_subscription

    def get(self, request):
        return Response(
            CurrentSubscriptionSerializer(
                self.request.user.useraccount.current_subscription
            ).data
        )
