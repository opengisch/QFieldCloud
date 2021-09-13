from django.contrib.auth import get_user_model
from qfieldcloud.core.models import (
    Delta,
    ExportJob,
    Job,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    Team,
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
    user_role = serializers.CharField(read_only=True)
    user_role_origin = serializers.CharField(read_only=True)
    private = serializers.BooleanField(allow_null=True, default=None)

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)
        owner_username = data.get("owner")

        if owner_username:
            try:
                internal_data["owner"] = User.objects.get(username=owner_username)
            except User.DoesNotExist:
                raise ValidationError(
                    {"owner": ["Invalid owner username"]},
                    code="invalid",
                )

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
            "user_role_origin",
        )
        model = Project


class CompleteUserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url if hasattr(obj, "useraccount") else None

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
    username_display = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url if hasattr(obj, "useraccount") else None

    def get_username_display(self, obj):
        if obj.user_type == obj.TYPE_TEAM:
            team = Team.objects.get(id=obj.id)
            return team.username.replace(f"@{team.team_organization.username}/", "")
        else:
            return obj.username

    class Meta:
        model = User
        fields = (
            "username",
            "user_type",
            "full_name",
            "avatar_url",
            "username_display",
        )
        read_only_fields = ("full_name", "avatar_url", "username_display")


class OrganizationSerializer(serializers.ModelSerializer):
    organization_owner = serializers.StringRelatedField()
    members = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    membership_role = serializers.CharField(read_only=True)
    membership_role_origin = serializers.CharField(read_only=True)
    membership_is_public = serializers.BooleanField()

    def get_members(self, obj):
        return [
            m["member__username"]
            for m in OrganizationMember.objects.filter(
                organization=obj, is_public=True
            ).values("member__username")
        ]

    def get_avatar_url(self, obj):
        return obj.useraccount.avatar_url if hasattr(obj, "useraccount") else None

    class Meta:
        model = Organization
        fields = (
            "username",
            "user_type",
            "email",
            "avatar_url",
            "members",
            "organization_owner",
            "membership_role",
            "membership_role_origin",
            "membership_is_public",
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
        return (
            obj.user.useraccount.avatar_url
            if hasattr(obj.user, "useraccount")
            else None
        )

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
    created_by = serializers.StringRelatedField()
    status = serializers.SerializerMethodField()
    output = serializers.CharField(source="last_feedback")

    def get_status(self, obj):
        if obj.last_status == Delta.Status.PENDING:
            return "STATUS_PENDING"
        elif obj.last_status == Delta.Status.STARTED:
            return "STATUS_BUSY"
        elif obj.last_status == Delta.Status.APPLIED:
            return "STATUS_APPLIED"
        elif obj.last_status == Delta.Status.CONFLICT:
            return "STATUS_CONFLICT"
        elif obj.last_status == Delta.Status.NOT_APPLIED:
            return "STATUS_NOT_APPLIED"
        elif obj.last_status == Delta.Status.ERROR:
            return "STATUS_ERROR"
        elif obj.last_status == Delta.Status.IGNORED:
            return "STATUS_IGNORED"
        elif obj.last_status == Delta.Status.UNPERMITTED:
            return "STATUS_UNPERMITTED"
        else:
            return "STATUS_ERROR"

    class Meta:
        model = Delta
        fields = (
            "id",
            "deltafile_id",
            "created_by",
            "created_at",
            "updated_at",
            "status",
            "output",
            "last_status",
            "last_feedback",
            "content",
        )


class ExportJobSerializer(serializers.ModelSerializer):
    layers = serializers.JSONField(source="feedback")
    status = serializers.SerializerMethodField()

    def get_status(self, obj):
        if obj.status == Job.Status.PENDING:
            return "STATUS_PENDING"
        elif obj.status == Job.Status.QUEUED:
            return "STATUS_BUSY"
        elif obj.status == Job.Status.STARTED:
            return "STATUS_BUSY"
        elif obj.status == Job.Status.STOPPED:
            return "STATUS_BUSY"
        elif obj.status == Job.Status.FINISHED:
            return "STATUS_EXPORTED"
        elif obj.status == Job.Status.FAILED:
            return "STATUS_ERROR"
        else:
            return "STATUS_ERROR"

    class Meta:
        model = ExportJob
        fields = ("status", "layers", "output")
