from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.utils import display_for_value
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.forms import ModelForm, fields, widgets
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import SafeText
from django.utils.translation import gettext_lazy as _
from unfold.admin import StackedInline, TabularInline
from unfold.decorators import action
from unfold.widgets import SELECT_CLASSES

from qfieldcloud.core.admin import (
    QFieldCloudModelAdmin,
    SecretInlineBase,
    format_text,
    model_admin_url,
    qfc_admin_site,
    redirect_to_add_secret,
    redirect_to_changelist,
)
from qfieldcloud.core.models import ProcessProjectfileJob, ProjectCollaborator, User
from qfieldcloud.core.utils import get_file_storage_choices
from qfieldcloud.core.utils2 import jobs
from qfieldcloud.filestorage.backend import QfcS3Boto3Storage
from qfieldcloud.filestorage.models import File
from qfieldcloud.project.enums import LayerErrorCode
from qfieldcloud.project.models import (
    SHARED_DATASETS_PROJECT_NAME,
    Project,
    ProjectSeed,
    QgisLayer,
    QgisProject,
)


def qgis_project_layers_list(qgis_project: "QgisProject") -> SafeText:
    headers = {
        "name": _("Name"),
        "layer_type": _("Type"),
        "geom_type": _("Geometry"),
        "is_valid": _("Valid"),
        "error": _("Error"),
    }
    rows = []
    for layer in qgis_project.layers.order_by("ordering"):
        if layer.error_code != LayerErrorCode.NO_ERROR:
            error_display = layer.get_error_code_display()
        else:
            error_display = "-"

        rows.append(
            {
                "name": model_admin_url(layer, layer.name),
                "layer_type": layer.get_layer_type_display(),
                "geom_type": layer.get_geom_type_display(),
                "is_valid": display_for_value(layer.is_valid, "-", boolean=True),
                "error": error_display,
            }
        )

    if not rows:
        return SafeText("-")

    return SafeText(
        render_to_string(
            "unfold/components/table.html",
            {
                "table": {
                    "headers": list(headers.values()),
                    "rows": [list(row.values()) for row in rows],
                },
            },
        )
    )


class ProjectFilesWidget(widgets.Input):
    template_name = "admin/project_files_widget.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["select_classes"] = " ".join(SELECT_CLASSES)

        return context


class OwnerTypeFilter(admin.SimpleListFilter):
    title = _("owner type")
    parameter_name = "owner_type"

    def lookups(self, request, model_admin):
        return [(User.Type.PERSON, "Person"), (User.Type.ORGANIZATION, "Organization")]

    def queryset(self, request, queryset):
        value = self.value()

        if value is None:
            return queryset

        return queryset.filter(owner__type=value)


class ProjectCollaboratorInline(TabularInline):
    model = ProjectCollaborator
    tab = True

    extra = 0

    readonly_fields = (
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    autocomplete_fields = ("collaborator",)


class UserProjectCollaboratorInline(TabularInline):
    model = ProjectCollaborator
    tab = True
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True

        return obj.type == User.Type.PERSON

    def has_direct_delete_permission(self, request, obj):
        if obj is None:
            return True

        return obj.type == User.Type.PERSON

    def has_change_permission(self, request, obj):
        if obj is None:
            return True

        return obj.type == User.Type.PERSON


class ProjectSeedInline(StackedInline):
    model = ProjectSeed
    tab = True
    extra = 1
    has_direct_delete_permission = False
    fk_name = "project"

    autocomplete_fields = ("clone_from_project",)

    fields = (
        "extent",
        "clone_from_project",
        "xlsform_file",
        "json2qgis_file",
        "settings__pre",
    )

    readonly_fields = (
        "extent",
        "clone_from_project",
        "settings__pre",
    )

    def settings__pre(self, instance: ProjectSeed) -> SafeText:
        return format_text(instance.settings, "json")

    def has_add_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Any | None = ...
    ) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Any | None = ...
    ) -> bool:
        return False


class QgisProjectInline(StackedInline):
    model = QgisProject
    tab = True
    extra = 0
    has_direct_delete_permission = False
    fk_name = "project"

    fields = (
        "name",
        "qgis_version",
        "crs",
        "extent",
        "area_of_interest",
        "background_color",
        "custom_properties__pre",
        "layers__list",
    )
    readonly_fields = fields

    @admin.display(description=_("Custom properties"))
    def custom_properties__pre(self, instance: QgisProject) -> SafeText:
        return format_text(instance.custom_properties, "json")

    @admin.display(description=_("Layers"))
    def layers__list(self, instance: QgisProject) -> SafeText:
        return qgis_project_layers_list(instance)

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class LayerAdmin(QFieldCloudModelAdmin):
    has_direct_delete_permission = False

    OWNER_LOOKUP = "qgis_project__project__owner"

    list_display = (
        "name",
        "qgis_project__link",
        "owner__link",
        "ordering",
        "layer_type",
        "geom_type",
        "is_valid",
        "error_code",
    )
    list_filter = (
        "layer_type",
        "geom_type",
        "is_valid",
        "is_localized",
        "error_code",
        (OWNER_LOOKUP, admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "name__icontains",
        "qgis_project__name__icontains",
    )
    ordering = ("qgis_project", "ordering")
    list_select_related = (OWNER_LOOKUP,)

    fields = (
        "qgis_project__link",
        "qgis_layer_id",
        "name",
        "ordering",
        "crs",
        "geom_type",
        "wkb_type_name",
        "layer_type",
        "provider_name",
        "datasource",
        "file_name",
        "is_valid",
        "is_localized",
        "error_code",
        "error_summary",
        "error_message",
        "provider_error_summary",
        "provider_error_message",
        "qfs_settings__pre",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    @admin.display(description=_("QGIS project"))
    def qgis_project__link(self, instance: QgisLayer) -> SafeText:
        return model_admin_url(
            instance.qgis_project.project, instance.qgis_project.name
        )

    @admin.display(description=_("Owner"), ordering=OWNER_LOOKUP)
    def owner__link(self, instance: QgisLayer) -> SafeText:
        return model_admin_url(instance.qgis_project.project.owner)

    @admin.display(description=_("QFieldSync settings"))
    def qfs_settings__pre(self, instance: QgisLayer) -> SafeText:
        return format_text(instance.qfs_settings, "json")

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


class ProjectForm(ModelForm):
    project_files = fields.CharField(
        disabled=True, required=False, widget=ProjectFilesWidget
    )

    class Meta:
        model = Project
        fields = "__all__"  # required for Django 3.x

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["file_storage"] = forms.ChoiceField(
            choices=get_file_storage_choices(), required=True
        )
        if File.objects.filter(project=self.instance).exists():
            self.fields["file_storage"].disabled = True

        self.fields["attachments_file_storage"] = forms.ChoiceField(
            choices=get_file_storage_choices(), required=True
        )
        if self.instance.has_attachments_files:
            self.fields["attachments_file_storage"].disabled = True
            self.fields["are_attachments_versioned"].disabled = True

    def clean_are_attachments_versioned(self):
        value = self.cleaned_data["are_attachments_versioned"]

        if value:
            return value

        # attachments can not be unversioned if attachments are stored on S3.
        attachment_storage_value = self.cleaned_data["attachments_file_storage"]
        attachment_storage = storages[attachment_storage_value]

        if isinstance(attachment_storage, QfcS3Boto3Storage):
            raise ValidationError(
                _(
                    "The '{}' attachments file storage is not compatible with unversioned attachment files."
                ).format(attachment_storage_value)
            )

        return value

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")

        if name and name.lower() == SHARED_DATASETS_PROJECT_NAME:
            if (
                self.instance.pk
                and self.instance.name.lower() == SHARED_DATASETS_PROJECT_NAME
            ):
                pass

            elif self.instance.has_the_qgis_file:
                raise ValidationError(
                    _(
                        "Cannot rename project to '{}' because it contains a QGIS project file."
                    ).format(name)
                )

        return cleaned_data


class ProjectAdmin(QFieldCloudModelAdmin):
    form = ProjectForm
    list_display = (
        "id",
        "name",
        "owner",
        "created_by",
        "is_public",
        "description",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_public",
        "created_at",
        "updated_at",
        OwnerTypeFilter,
    )
    fields = (
        "id",
        "project_type",
        "name",
        "description",
        "is_public",
        "public_collaborator_role",
        "owner",
        "created_by",
        "status",
        "status_code",
        "the_qgis_file",
        "qgis_version",
        "overwrite_conflicts",
        "has_restricted_projectfiles",
        "file_storage_bytes",
        "storage_keep_versions",
        "packaging_offliner",
        "created_at",
        "updated_at",
        "data_last_updated_at",
        "restricted_data_last_updated_at",
        "data_last_packaged_at",
        "project_details__pre",
        "locked_at",
        "is_featured",
        "file_storage",
        "file_storage_migrated_at",
        "attachments_file_storage",
        "are_attachments_versioned",
        "is_attachment_download_on_demand",
        "project_files",
    )
    readonly_fields = (
        "id",
        "created_by",
        "status",
        "status_code",
        "file_storage_bytes",
        "created_at",
        "updated_at",
        "data_last_updated_at",
        "restricted_data_last_updated_at",
        "data_last_packaged_at",
        "project_details__pre",
        "locked_at",
        "file_storage_migrated_at",
        "the_qgis_file",
        "qgis_version",
    )
    inlines = (
        ProjectSeedInline,
        SecretInlineBase,
        ProjectCollaboratorInline,
        QgisProjectInline,
    )
    search_fields = (
        "id",
        "name__icontains",
        "owner__username__iexact",
    )
    autocomplete_fields = ("owner",)

    ordering = ("-updated_at",)

    actions_detail = (
        {
            "title": _("Actions"),
            "icon": "bolt",
            "items": [
                "run_process_projectfile_job",
                "add_secret",
            ],
        },
        {
            "title": _("Related"),
            "icon": "link",
            "items": ["related_jobs", "related_faulty_deltafiles"],
        },
    )

    search_parser_config = {
        "owner": {
            "filter": "owner__username__iexact",
        },
        "collaborator": {
            "filter": "user_roles__user__username__iexact",
            "extra_filters": {
                "is_public": False,
            },
        },
    }

    def get_form(self, *args, **kwargs):
        help_texts = {
            "file_storage_bytes": _(
                "This value represents the total size of the project in bytes, including the space taken by the stored file versions."
            )
        }
        kwargs.update({"help_texts": help_texts})
        return super().get_form(*args, **kwargs)

    def project_files(self, instance):
        return instance.pk

    def project_details__pre(self, instance):
        if instance.project_details is None:
            return ""

        return format_text(instance.project_details, "json")

    def save_formset(self, request, form, formset, change):
        for form_obj in formset:
            if isinstance(form_obj.instance, ProjectCollaborator):
                # add created_by only if it's a newly created collaborator
                if form_obj.instance.id is None:
                    form_obj.instance.created_by = request.user

                form_obj.instance.updated_by = request.user

        super().save_formset(request, form, formset, change)

    def has_add_secret_permission(
        self, request: HttpRequest, object_id: str | None = None
    ) -> bool:
        return request.user.has_perm("core.add_secret")  # type: ignore[union-attr]

    @action(
        description=_("Add secret"),
        url_path="add-secret",
        icon="key",
        permissions=["add_secret"],
    )
    def add_secret(self, request: HttpRequest, object_id: str) -> HttpResponse:
        return redirect_to_add_secret("project", object_id)

    @action(
        description=_("Run process projectfile job"),
        url_path="run-process-projectfile-job",
        icon="play_arrow",
    )
    def run_process_projectfile_job(
        self, request: HttpRequest, object_id: str
    ) -> HttpResponse:
        project = Project.objects.get(pk=object_id)
        jobs.queue_job(project, ProcessProjectfileJob)
        return HttpResponseRedirect(
            reverse("admin:project_project_change", args=[object_id])
        )

    @action(
        description=_("Project jobs"),
        url_path="related-jobs",
        icon="work_history",
    )
    def related_jobs(self, request: HttpRequest, object_id: str) -> HttpResponse:
        return redirect_to_changelist("admin:core_job_changelist", object_id)

    @action(
        description=_("Faulty deltafiles"),
        url_path="related-faulty-deltafiles",
        icon="report",
    )
    def related_faulty_deltafiles(
        self, request: HttpRequest, object_id: str
    ) -> HttpResponse:
        return redirect_to_changelist(
            "admin:core_faultydeltafile_changelist", object_id
        )


qfc_admin_site.register(Project, ProjectAdmin)
qfc_admin_site.register(QgisLayer, LayerAdmin)
