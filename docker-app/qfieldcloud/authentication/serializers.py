from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import AuthToken

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """Based on https://github.com/Tivix/django-rest-auth/blob/rest_auth/serializers.py#L19"""

    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(style={"input_type": "password"})

    def authenticate(self, **kwargs):
        return authenticate(self.context["request"], **kwargs)

    def _validate_email(self, email, password):
        user = None

        if email and password:
            user = self.authenticate(email=email, password=password)
        else:
            msg = _('Must include "email" and "password".')
            raise ValidationError(msg)

        return user

    def _validate_username(self, username, password):
        user = None

        if username and password:
            user = self.authenticate(username=username, password=password)
        else:
            msg = _('Must include "username" and "password".')
            raise ValidationError(msg)

        return user

    def _validate_username_email(self, username, email, password):
        user = None

        if email and password:
            user = self.authenticate(email=email, password=password)
        elif username and password:
            user = self.authenticate(username=username, password=password)
        else:
            msg = _('Must include either "username" or "email" and "password".')
            raise ValidationError(msg)

        return user

    def validate(self, attrs):
        username = attrs.get("username")
        email = attrs.get("email")
        password = attrs.get("password")

        user = None

        if "allauth" in settings.INSTALLED_APPS:
            from allauth.account import app_settings

            # Authentication through email
            if (
                app_settings.AUTHENTICATION_METHOD
                == app_settings.AuthenticationMethod.EMAIL
            ):
                user = self._validate_email(email, password)

            # Authentication through username
            elif (
                app_settings.AUTHENTICATION_METHOD
                == app_settings.AuthenticationMethod.USERNAME
            ):
                user = self._validate_username(username, password)

            # Authentication through either username or email
            else:
                user = self._validate_username_email(username, email, password)

        else:
            # Authentication without using allauth
            if email:
                try:
                    username = User.objects.get(email__iexact=email).get_username()
                except User.DoesNotExist:
                    pass

            if username:
                user = self._validate_username_email(username, "", password)

        # Did we get back an active user?
        if user:
            if not user.is_active:
                msg = _("User account is disabled.")
                raise ValidationError(msg)
        else:
            msg = _("Unable to log in with provided credentials.")
            raise ValidationError(msg)

        attrs["user"] = user
        return attrs


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
