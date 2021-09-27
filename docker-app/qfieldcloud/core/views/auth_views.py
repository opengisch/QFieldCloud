from qfieldcloud.core.models import AuthToken
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response


class AuthTokenView(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token = AuthToken.create_from_request(request, user)
        avatar_url = (
            user.useraccount.avatar_url if hasattr(user, "useraccount") else None
        )
        return Response(
            {
                "token": token.key,
                "username": user.username,
                "email": user.email,
                "avatar_url": avatar_url,
            }
        )
