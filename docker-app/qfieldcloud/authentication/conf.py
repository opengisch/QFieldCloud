from django.conf import settings

settings.QFIELDCLOUD_LOGIN_SERIALIZER = getattr(
    settings,
    "QFIELDCLOUD_LOGIN_SERIALIZER",
    "qfieldcloud.authentication.serializers.LoginSerializer",
)

settings.QFIELDCLOUD_TOKEN_SERIALIZER = getattr(
    settings,
    "QFIELDCLOUD_TOKEN_SERIALIZER",
    "qfieldcloud.authentication.serializers.TokenSerializer",
)

settings.QFIELDCLOUD_USER_SERIALIZER = getattr(
    settings,
    "QFIELDCLOUD_USER_SERIALIZER",
    "qfieldcloud.authentication.serializers.UserSerializer",
)
