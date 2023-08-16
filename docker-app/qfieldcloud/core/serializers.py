import os
from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import (
    ApplyJob,
    Delta,
    Job,
    Organization,
    OrganizationMember,
    PackageJob,
    ProcessProjectfileJob,
    Project,
    ProjectCollaborator,
    Team,
)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

User = get_user_model()


def get_avatar_url(user: User) -> Optional[str]:
    if hasattr(user, "useraccount") and user.useraccount.avatar_url:
        site = Site.objects.get_current()
        port = os.environ.get("WEB_HTTPS_PORT")
        port = f":{port}" if port != "443" else ""
        return f"https://{site.domain}{port}{user.useraccount.avatar_url}"
    return None


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
        else:
            if not self.instance or not self.instance.owner:
                internal_data["owner"] = self.context["request"].user

        if "private" in internal_data:
            if internal_data["private"] is not None:
                internal_data["is_public"] = not internal_data["private"]

            del internal_data["private"]

        return internal_data

    def validate(self, data):
        if data.get("name") is not None:
            owner = self.instance.owner if self.instance else data["owner"]
            projects_qs = Project.objects.filter(
                owner=owner,
                name=data["name"],
            )

            if self.instance:
                projects_qs = projects_qs.exclude(id=self.instance.id)

            matching_projects = projects_qs.count()

            if matching_projects != 0:
                raise exceptions.ProjectAlreadyExistsError()

        return data

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
            "data_last_packaged_at",
            "data_last_updated_at",
            "can_repackage",
            "needs_repackaging",
            "status",
            "user_role",
            "user_role_origin",
        )
        model = Project


class CompleteUserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    def get_avatar_url(self, obj):
        return get_avatar_url(obj)

    class Meta:
        model = User
        fields = (
            "username",
            "type",
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
        return get_avatar_url(obj)

    def get_username_display(self, obj):
        if obj.type == obj.Type.TEAM:
            team = Team.objects.get(id=obj.id)
            return team.username.replace(f"@{team.team_organization.username}/", "")
        else:
            return obj.username

    class Meta:
        model = User
        fields = (
            "username",
            "type",
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
    membership_is_public = serializers.BooleanField(
        read_only=True, source="membership_role_is_public"
    )

    def get_members(self, obj):
        return [
            m["member__username"]
            for m in OrganizationMember.objects.filter(
                organization=obj, is_public=True
            ).values("member__username")
        ]

    def get_avatar_url(self, obj):
        return get_avatar_url(obj)

    class Meta:
        model = Organization
        fields = (
            "username",
            "type",
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
    username = serializers.CharField(source="user.username")
    expires_at = serializers.DateTimeField()
    type = serializers.CharField(source="user.type")
    first_name = serializers.CharField(source="user.first_name")
    last_name = serializers.CharField(source="user.last_name")
    full_name = serializers.CharField(source="user.full_name")
    token = serializers.CharField(source="key")
    email = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    def get_email(self, obj):
        return obj.user.email

    def get_avatar_url(self, obj):
        return get_avatar_url(obj.user)

    class Meta:
        model = AuthToken
        fields = (
            "token",
            "expires_at",
            "username",
            "type",
            "email",
            "avatar_url",
            "first_name",
            "last_name",
            "full_name",
        )
        read_only_fields = (
            "token",
            "expires_at",
            "full_name",
            "avatar_url",
        )


class StatusChoiceField(serializers.ChoiceField):
    def to_representation(self, obj):
        return self._choices[obj]

    def to_internal_value(self, data):
        for i in self._choices:
            if self._choices[i] == data:
                return i
        raise serializers.ValidationError(
            "Invalid status. Acceptable values are {}.".format(
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
    # TODO layers used to hold information about layer validity. No longer needed.
    layers = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField(initial="STATUS_ERROR")

    def get_initial(self):
        if self.instance is None:
            return {
                "layers": None,
                "output": "",
                "status": "STATUS_ERROR",
            }
        return super().get_initial()

    def get_layers(self, obj):
        if not obj.feedback:
            return None

        if obj.status != Job.Status.FINISHED:
            return None

        if obj.feedback.get("feedback_version") == "2.0":
            return obj.feedback["outputs"]["qgis_layers_data"]["layers_by_id"]
        else:
            steps = obj.feedback.get("steps", [])
            if len(steps) > 2 and steps[1].get("stage", 1) == 2:
                return steps[1]["outputs"]["layer_checks"]

        return None

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
        model = PackageJob
        fields = ("status", "layers", "output")


class JobMixin:
    project_id = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)
        internal_data["created_by"] = self.context["request"].user
        internal_data["project"] = Project.objects.get(pk=data.get("project_id"))

        return internal_data

    def get_lastest_not_finished_job(self) -> Optional[Job]:
        ModelClass: Job = self.Meta.model
        last_active_job = (
            ModelClass.objects.filter(
                project=self.initial_data.get("project_id"),
                status__in=[Job.Status.PENDING, Job.Status.QUEUED, Job.Status.STARTED],
            )
            .only("id")
            .order_by("-started_at", "-created_at")
            .last()
        )

        return last_active_job

    class Meta:
        model = Job
        fields = (
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "project_id",
            "started_at",
            "status",
            "type",
            "updated_at",
            "feedback",
            "output",
        )

        read_only_fields = (
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "started_at",
            "status",
            "updated_at",
            "feedback",
            "output",
        )


class PackageJobSerializer(JobMixin, serializers.ModelSerializer):
    def get_lastest_not_finished_job(self) -> Optional[Job]:
        job = super().get_lastest_not_finished_job()
        if job:
            return job

        internal_value = self.to_internal_value(self.initial_data)

        if not internal_value["project"].project_filename:
            raise exceptions.NoQGISProjectError()
        return None

    class Meta(JobMixin.Meta):
        model = PackageJob
        allow_parallel_jobs = False


class ApplyJobSerializer(JobMixin, serializers.ModelSerializer):
    class Meta(JobMixin.Meta):
        model = ApplyJob
        allow_parallel_jobs = True


class ProcessProjectfileJobSerializer(JobMixin, serializers.ModelSerializer):
    class Meta(JobMixin.Meta):
        model = ProcessProjectfileJob
        allow_parallel_jobs = True


class JobSerializer(serializers.ModelSerializer):
    def get_lastest_not_finished_job(self):
        return None

    def get_fields(self, *args, **kwargs):
        fields = super().get_fields(*args, **kwargs)
        request = self.context.get("request")

        if request and "job_id" not in request.parser_context.get("kwargs", {}):
            fields.pop("output", None)
            fields.pop("feedback", None)
            fields.pop("layers", None)

        return fields

    class Meta:
        model = Job
        fields = (
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "project_id",
            "started_at",
            "status",
            "type",
            "updated_at",
            "feedback",
            "output",
        )
        read_only_fields = (
            "id",
            "created_at",
            "created_by",
            "finished_at",
            "started_at",
            "status",
            "updated_at",
            "feedback",
            "output",
        )
        order_by = "-created_at"
        allow_parallel_jobs = True


class FileVersionSerializer(serializers.Serializer):
    """NOTE not used for actual serialization, but for documentation suing Django Spectacular."""

    size = serializers.IntegerField()
    md5sum = serializers.CharField()
    version_id = serializers.CharField()
    last_modified = serializers.DateTimeField()
    is_latest = serializers.BooleanField(required=False)
    display = serializers.CharField()
    sha256 = serializers.CharField(required=False)


class FileSerializer(serializers.Serializer):
    """NOTE not used for actual serialization, but for documentation suing Django Spectacular."""

    versions = serializers.ListField(child=FileVersionSerializer())
    sha256 = serializers.CharField(required=False)
    name = serializers.CharField()
    size = serializers.IntegerField()
    md5sum = serializers.CharField()
    last_modified = serializers.DateTimeField()
    is_attachment = serializers.BooleanField()


class LatestPackageSerializer(serializers.Serializer):
    """NOTE not used for actual serialization, but for documentation suing Django Spectacular."""

    files = serializers.ListSerializer(child=FileSerializer())
    layers = serializers.JSONField()
    status = serializers.ChoiceField(Job.Status)
    package_id = serializers.UUIDField()
    packaged_at = serializers.DateTimeField()
    data_last_updated_at = serializers.DateTimeField()
