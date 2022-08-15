from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AuthToken

User = get_user_model()


class TokenSerializer(serializers.ModelSerializer):
    expires_at = serializers.DateTimeField()
    token = serializers.CharField(source="key")

    class Meta:
        model = AuthToken
        fields = (
            "token",
            "expires_at",
        )
        read_only_fields = (
            "token",
            "expires_at",
        )


class UserSerializer(serializers.ModelSerializer):
    """
    User model w/o password
    """

    class Meta:
        model = User
        fields = ("pk", "username", "email", "first_name", "last_name")
        read_only_fields = ("email",)
