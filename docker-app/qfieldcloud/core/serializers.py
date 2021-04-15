from django.contrib.auth import get_user_model
from qfieldcloud.core.models import (
    Delta,
    Exportation,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
)
from rest_framework import serializers
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError

User = get_user_model()


class UserSerializer:
    class Meta:
        model = User
        fields = ("username",)


class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField()
    user_role = serializers.SerializerMethodField()
    private = serializers.BooleanField(allow_null=True, default=None)

    def get_user_role(self, obj):
        return getattr(obj, "user_role", None)

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)
        owner_username = data.get("owner")
        try:
            owner = User.objects.get(username=owner_username)
        except User.DoesNotExist:
            raise ValidationError(
                {"owner": ["Invalid owner username"]},
                code="invalid",
            )
        internal_data["owner"] = owner

        if "private" in internal_data:
            if internal_data["private"] is not None:
                internal_data["is_public"] = not internal_data["private"]

            del internal_data["private"]

        return internal_data

    class Meta:
        fields = (
            "id",
            "name",
            "owner",
            "description",
            # remove "private" field one day
            "private",
            "is_public",
            "created_at",
            "updated_at",
            "user_role",
        )
        model = Project


class CompleteUserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url

    class Meta:
        model = User
        fields = (
            "username",
            "user_type",
            "full_name",
            "email",
            "avatar_url",
            "first_name",
            "last_name",
        )
        read_only_fields = ("full_name", "avatar_url")


class PublicInfoUserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url

    class Meta:
        model = User
        fields = ("username", "user_type", "full_name", "avatar_url")
        read_only_fields = ("full_name", "avatar_url")


class OrganizationSerializer(serializers.ModelSerializer):
    organization_owner = serializers.StringRelatedField()
    members = serializers.StringRelatedField(many=True)
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url

    class Meta:
        model = Organization
        fields = (
            "username",
            "user_type",
            "email",
            "avatar_url",
            "members",
            "organization_owner",
        )


class ProjectCollaboratorSerializer(serializers.ModelSerializer):
    collaborator = serializers.StringRelatedField()
    role = serializers.CharField()

    class Meta:
        model = ProjectCollaborator
        fields = ("collaborator", "role")


class OrganizationMemberSerializer(serializers.ModelSerializer):
    member = serializers.StringRelatedField()
    role = serializers.CharField()

    class Meta:
        model = OrganizationMember
        fields = ("member", "role")


class TokenSerializer(serializers.ModelSerializer):
    username = serializers.StringRelatedField(source="user")
    token = serializers.CharField(source="key")
    email = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_email(self, obj):
        return obj.user.email

    def get_avatar_url(self, obj):
        return obj.user.useraccount.avatar_url

    class Meta:
        model = Token
        fields = ("token", "username", "email", "avatar_url")


class StatusChoiceField(serializers.ChoiceField):
    def to_representation(self, obj):
        return self._choices[obj]

    def to_internal_value(self, data):
        for i in self._choices:
            if self._choices[i] == data:
                return i
        raise serializers.ValidationError(
            "Invalid status. Acceptable values are {0}.".format(
                list(self._choices.values())
            )
        )


class DeltaSerializer(serializers.ModelSerializer):
    status = StatusChoiceField(choices=Delta.STATUS_CHOICES)

    class Meta:
        model = Delta
        fields = (
            "id",
            "deltafile_id",
            "created_at",
            "updated_at",
            "status",
            "output",
            "content",
        )


class ExportationSerializer(serializers.ModelSerializer):
    status = StatusChoiceField(choices=Exportation.STATUS_CHOICES)
    layers = serializers.JSONField(source="exportlog")

    class Meta:
        model = Exportation
        fields = ("status", "layers", "output")
