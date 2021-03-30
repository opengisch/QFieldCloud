import json
import time

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin, messages
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.auth.models import Group
from django.contrib.postgres.fields import JSONField
from django.forms import widgets
from django.http.response import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.utils.html import escape, format_html
from django.utils.safestring import SafeText
from qfieldcloud.core import exceptions, utils
from qfieldcloud.core.models import (
    Delta,
    Exportation,
    Geodb,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    User,
    UserAccount,
)


class PrettyJSONWidget(widgets.Textarea):
    def format_value(self, value):
        text_value = json.dumps(json.loads(value), indent=2, sort_keys=True)

        row_lengths = [len(r) for r in text_value.split("\n")]

        self.attrs["rows"] = min(max(len(row_lengths) + 2, 10), 30)
        self.attrs["cols"] = min(max(max(row_lengths) + 2, 40), 120)
        return SafeText(text_value)


def model_admin_url(obj, name: str = None) -> str:
    url = resolve_url(admin_urlname(obj._meta, SafeText("change")), obj.pk)
    return format_html('<a href="{}">{}</a>', url, name or str(obj))


def format_pre(value):
    return format_html("<pre>{}</pre>", escape(value))


def format_pre_json(value):
    if value:
        text_value = json.dumps(value, indent=2, sort_keys=True)
        return format_pre(text_value)
    else:
        return format_pre(value)


class UserAdmin(admin.ModelAdmin):
    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "is_superuser",
        "is_staff",
        "is_active",
        "date_joined",
        "user_type",
        "useraccount",
    )
    list_filter = ("user_type", "useraccount")

    def save_model(self, request, obj, form, change):
        # Set the password to the value in the field if it's changed.
        if obj.pk:
            if "password" in form.changed_data:
                obj.set_password(obj.password)
        else:
            obj.set_password(obj.password)
        obj.save()


class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "owner",
        "private",
        "description",
        "created_at",
        "updated_at",
    )
    list_filter = ("private",)
    fields = ("name", "description", "private", "owner", "storage_size")
    readonly_fields = ("storage_size",)


class DeltaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deltafile_id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status",)

    actions = (
        "set_status_pending",
        "set_status_ignored",
        "set_status_unpermitted",
        "apply_selected_deltas",
    )

    readonly_fields = (
        "project",
        "deltafile_id",
        "output__pre",
        "created_at",
        "updated_at",
    )
    fields = (
        "project",
        "deltafile_id",
        "status",
        "created_at",
        "updated_at",
        "content",
        "output__pre",
    )
    search_fields = (
        "project__name__iexact",
        "project__owner__username__iexact",
        "output__icontains",
        "deltafile_id",
        "id",
    )

    formfield_overrides = {JSONField: {"widget": PrettyJSONWidget}}

    change_form_template = "admin/delta_change_form.html"

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    def output__pre(self, instance):
        return format_pre_json(instance.output)

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def set_status_pending(self, request, queryset):
        queryset.update(status=Delta.STATUS_PENDING)

    def set_status_ignored(self, request, queryset):
        queryset.update(status=Delta.STATUS_IGNORED)

    def set_status_unpermitted(self, request, queryset):
        queryset.update(status=Delta.STATUS_UNPERMITTED)

    def response_change(self, request, delta):
        if "_apply_delta_btn" in request.POST:
            project_file = utils.get_qgis_project_file(delta.project.id)

            utils.apply_deltas(
                str(delta.project.id),
                project_file,
                delta.project.overwrite_conflicts,
                delta_ids=[str(delta.id)],
            )

            if project_file is None:
                self.message_user(request, "Missing project file")
                raise exceptions.NoQGISProjectError()

            self.message_user(request, "Delta application started")

            # we need to sleep 1 second, just to make surethe apply delta started
            time.sleep(1)

            return HttpResponseRedirect(".")

        return super().response_change(request, delta)


class ExportationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "created_at")
    list_select_related = ("project", "project__owner")
    actions = None
    exclude = ("exportlog", "output")

    readonly_fields = (
        "project",
        "status",
        "created_at",
        "updated_at",
        "output__pre",
        "exportlog__pre",
    )

    search_fields = (
        "id",
        "exportlog__icontains",
        "project__name__iexact",
        "project__owner__username__iexact",
    )

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def output__pre(self, instance):
        return format_pre(instance.output)

    def exportlog__pre(self, instance):
        return format_pre_json(instance.exportlog)

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class UserAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "account_type",
        "storage_limit_mb",
        "db_limit_mb",
        "synchronizations_per_months",
    )
    list_filter = ("account_type",)


class GeodbAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "username",
        "dbname",
        "hostname",
        "port",
        "created_at",
        "size",
    )

    fields = ("user", "username", "dbname", "hostname", "port", "created_at", "size")

    readonly_fields = ("size", "created_at")

    def save_model(self, request, obj, form, change):
        # Only on creation
        if not change:
            messages.add_message(
                request,
                messages.WARNING,
                "The password is (shown only once): {}".format(obj.password),
            )
        super().save_model(request, obj, form, change)


admin.site.register(User, UserAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Delta, DeltaAdmin)
admin.site.register(Exportation, ExportationAdmin)
admin.site.register(UserAccount, UserAccountAdmin)
admin.site.register(Geodb, GeodbAdmin)

admin.site.register(Organization)
admin.site.register(OrganizationMember)
admin.site.register(ProjectCollaborator)

admin.site.unregister(Group)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
