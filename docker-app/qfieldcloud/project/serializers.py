from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from qfieldcloud.core import exceptions
from qfieldcloud.core.models import (
    BasemapProvider,
    BasemapStyle,
    Team,
    User,
)
from qfieldcloud.project.models import (
    SHARED_DATASETS_PROJECT_NAME,
    Project,
    ProjectSeed,
)
from qfieldcloud.subscription.exceptions import QuotaError


@extend_schema_serializer(deprecate_fields=["is_shared_datasets_project"])
class ProjectSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField()
    project_type = serializers.ChoiceField(
        choices=[
            (choice.value, choice.label)
            for choice in Project.CONFIGURABLE_PROJECT_TYPES
        ],
        required=False,
    )
    user_role = serializers.CharField(read_only=True)
    user_role_origin = serializers.CharField(read_only=True)
    private = serializers.BooleanField(allow_null=True, default=None)
    shared_datasets_project_id = serializers.SerializerMethodField(read_only=True)
    needs_repackaging = serializers.SerializerMethodField()
    seed = serializers.JSONField(
        required=False,
        write_only=True,
        help_text="The seed data to use to create the project. if `clone_from_project` is provided, only the extent field is allowed.",
    )
    xlsform_file = serializers.FileField(
        required=False,
        write_only=True,
        help_text="The XLSForm file to use to create the project. Ignored if `clone_from_project` is provided.",
    )
    clone_from_project = serializers.UUIDField(
        required=False,
        write_only=True,
        help_text="The project to clone from. If provided, the project will be created as a clone of the specified project.",
    )

    def get_shared_datasets_project_id(self, obj: Project) -> str | None:
        if obj.shared_datasets_project:
            return str(obj.shared_datasets_project.id)
        else:
            return None

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

        clone_from_id = internal_data.get("clone_from_project")
        if clone_from_id:
            try:
                source_project = Project.objects.get(id=clone_from_id)
            except Project.DoesNotExist:
                raise ValidationError({"clone_from_project": "Project not found."})

            for field in ProjectSerializer.Meta.clonable_fields:
                if field not in internal_data:
                    internal_data[field] = getattr(source_project, field)

            internal_data["clone_from_project"] = source_project

        return internal_data

    def validate(self, data):
        if data.get("name") is not None:
            if self.instance:
                owner = self.instance.owner
            else:
                owner = data["owner"]

            projects_qs = Project.objects.filter(
                owner=owner,
                name=data["name"],
            )

            if self.instance:
                projects_qs = projects_qs.exclude(id=self.instance.id)

            matching_projects = projects_qs.count()

            if matching_projects != 0:
                raise exceptions.ProjectAlreadyExistsError()

            if data["name"].lower() == SHARED_DATASETS_PROJECT_NAME:
                if (
                    self.instance
                    and self.instance.name.lower() == SHARED_DATASETS_PROJECT_NAME
                ):
                    pass

                elif self.instance and self.instance.has_the_qgis_file:
                    raise exceptions.QGISProjectFileNotAllowedError(
                        "QGIS project files are not allowed in shared datasets projects."
                    )

        source_project = data.get("clone_from_project")
        seed = data.get("seed")
        xlsform_file = data.get("xlsform_file")

        if source_project:
            if source_project.is_shared_datasets_project:
                raise exceptions.NotCloneableProjectError(
                    "The 'shared_datasets' project cannot be cloned."
                )

            if seed:
                if not seed.get("extent"):
                    raise ValidationError({"seed": "Extent is required in seed."})

                if len(seed.keys()) > 1:
                    raise ValidationError(
                        {"seed": "Only extent field is allowed in seed."}
                    )

            target_owner = data.get("owner") or self.context["request"].user
            if (
                source_project.file_storage_bytes
                > target_owner.useraccount.storage_free_bytes
            ):
                raise QuotaError("Insufficient storage quota.")
        else:
            if xlsform_file and not seed:
                raise ValidationError(
                    {
                        "xlsform_file": [
                            "Cannot upload an XLSForm file without seed data."
                        ]
                    }
                )

            if seed:
                provider = seed.get("basemap_provider", "none")
                url = seed.get("basemap_url", "")
                if provider == "custom" and not url:
                    raise ValidationError(
                        {
                            "seed": [
                                "When configuring basemaps in the project's seed, `basemap_url` is required when `basemap_provider` is set to `custom`."
                            ]
                        }
                    )

        return data

    def create(self, validated_data):
        # remove non-model fields before saving
        validated_data.pop("seed", None)
        validated_data.pop("xlsform_file", None)
        validated_data.pop("clone_from_project", None)
        return super().create(validated_data)

    def get_needs_repackaging(self, obj: Project) -> bool:
        request = self.context.get("request")

        if request:
            return obj.needs_repackaging(request.user)  # type: ignore[attr-defined]

        return False

    class Meta:
        fields = (
            "id",
            "name",
            "project_type",
            "owner",
            "description",
            # remove "private" field one day
            "private",
            "is_public",
            "created_at",
            "updated_at",
            "data_last_packaged_at",
            "data_last_updated_at",
            "restricted_data_last_updated_at",
            "can_repackage",
            "needs_repackaging",
            "status",
            "user_role",
            "user_role_origin",
            "shared_datasets_project_id",
            "is_shared_datasets_project",
            "is_featured",
            "is_attachment_download_on_demand",
            "has_restricted_projectfiles",
            "overwrite_conflicts",
            "file_storage_bytes",
            "seed",
            "xlsform_file",
            "clone_from_project",
            "the_qgis_file_name",
        )
        read_only_fields = (
            "private",
            "created_at",
            "updated_at",
            "data_last_packaged_at",
            "data_last_updated_at",
            "restricted_data_last_updated_at",
            "can_repackage",
            "needs_repackaging",
            "status",
            "user_role",
            "user_role_origin",
            "shared_datasets_project_id",
            "is_shared_datasets_project",
            "file_storage_bytes",
            "the_qgis_file_name",
        )
        clonable_fields = {
            "description",
            "is_public",
            "is_featured",
            "is_attachment_download_on_demand",
            "has_restricted_projectfiles",
            "overwrite_conflicts",
        }
        model = Project


class ProjectDetailSerializer(ProjectSerializer):
    """`ProjectSerializer` with the caller's teams in the project owning organization."""

    teams = serializers.SerializerMethodField()

    def get_teams(self, obj: Project) -> list[str]:
        """Returns the caller's team names in the project's owning organization, without the `@organization/` prefix.

        Empty when a person owns the project or the caller is in no team.
        """
        # A person owns the project, so it has no teams.
        if obj.owner.is_person:
            return []

        request = self.context["request"]

        teams = Team.objects.filter(
            team_organization=obj.owner.organization,
            members__member=request.user,
        ).select_related("team_organization")

        team_names = []
        for team in teams:
            team_names.append(team.teamname)

        return team_names

    class Meta(ProjectSerializer.Meta):
        fields = (*ProjectSerializer.Meta.fields, "teams")  # type: ignore[assignment]
        read_only_fields = (
            *ProjectSerializer.Meta.read_only_fields,
            "teams",
        )  # type: ignore[assignment]


class ProjectThumbnailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ("thumbnail",)


class ProjectSeedSerializer(serializers.ModelSerializer):
    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        model = ProjectSeed
        fields = "__all__"

    name = serializers.StringRelatedField(source="project.name")
    extent = serializers.SerializerMethodField()
    clone_from_project = serializers.PrimaryKeyRelatedField(read_only=True)
    settings = serializers.JSONField()
    # TODO @suricactus: QF-7258 Adding a project extent field on project creation, see https://app.clickup.com/t/2192114/QF-7258
    crs = serializers.CharField(default="EPSG:3857")

    def get_extent(self, obj: ProjectSeed) -> dict[str, Any] | None:
        if obj.extent is None:
            return None

        return obj.extent.extent


class ProjectSeedRequestSerializer(serializers.Serializer):
    """Documentation only schema for the `seed` request object.

    `ProjectSerializer.seed` is a plain `JSONField`. This serializer exists so
    `@extend_schema` can render the real keys instead of a string.
    """

    extent = serializers.CharField(
        required=False,
        help_text=(
            "Project extent in EPSG:4326 as `minX, minY, maxX, maxY`. "
            "When `clone_from_project` is provided, this is the only allowed key."
        ),
    )
    basemap_provider = serializers.ChoiceField(
        choices=BasemapProvider.choices,
        required=False,
        default=BasemapProvider.NONE,
        help_text="Basemap provider to seed the project with.",
    )
    basemap_style = serializers.ChoiceField(
        choices=BasemapStyle.choices,
        required=False,
        default=BasemapStyle.STANDARD,
        help_text="Basemap style. Only used when `basemap_provider` is set.",
    )
    basemap_url = serializers.CharField(
        required=False,
        help_text="XYZ tile URL. Required when `basemap_provider` is `custom`.",
    )


class ProjectCreateRequestSerializer(ProjectSerializer):
    """Documentation only request schema for `POST /api/v1/projects/`."""

    # Here `owner` and `seed` are overridden read-only / loosely-typed fields on `ProjectSerializer`
    # purely to shape the generated schema, so the type mismatch is expected.
    owner = serializers.CharField(  # type: ignore[assignment]
        required=False,
        help_text=(
            "Username of the project owner. Can be the authenticated user or an "
            "organization they are a member of. Defaults to the authenticated "
            "user when omitted."
        ),
    )
    seed = ProjectSeedRequestSerializer(  # type: ignore[assignment]
        required=False,
        help_text=(
            "Seed data used to pre-populate the project. An `xlsform_file` upload "
            "makes the request `multipart/form-data`, and `seed` then has to be a "
            "JSON-encoded string. If `clone_from_project` is provided, only the "
            "`extent` field is allowed."
        ),
    )
    xlsform_file = extend_schema_field(OpenApiTypes.BINARY)(serializers.FileField)(
        required=False,
        write_only=True,
        help_text=(
            "The XLSForm file to use to create the project. Requires `seed` and a "
            "`multipart/form-data` request. Ignored if `clone_from_project` is "
            "provided."
        ),
    )


@extend_schema_serializer(
    exclude_fields=["xlsform_file"],
)
class ProjectCreateJSONRequestSerializer(ProjectCreateRequestSerializer):
    """Documentation only `application/json` variant of the create request.

    `xlsform_file` is dropped here: a file can only be sent in a
    `multipart/form-data` request, so it lives only on
    `ProjectCreateRequestSerializer`.
    """


@extend_schema_serializer(
    exclude_fields=["seed", "xlsform_file", "clone_from_project"],
)
class ProjectUpdateRequestSerializer(ProjectCreateRequestSerializer):
    """Documentation only request schema for project update and partial update.

    Same as `ProjectCreateRequestSerializer` without the create-only fields
    `seed`, `xlsform_file` and `clone_from_project`.
    """
