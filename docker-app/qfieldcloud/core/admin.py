import json

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin, messages
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.auth.models import Group
from django.shortcuts import resolve_url
from django.utils.html import escape, format_html
from django.utils.safestring import SafeText
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


def model_admin_url(obj, name: str = None) -> str:
    url = resolve_url(admin_urlname(obj._meta, SafeText("change")), obj.pk)
    return format_html('<a href="{}">{}</a>', url, name or str(obj))


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
    list_display = ("id", "project", "status", "created_at", "updated_at")
    list_filter = ("status",)
    actions = None
    readonly_fields = ("project", "content", "output")

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    # TODO: add a custom action to re-apply the deltafile


class ExportationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("project", "status", "created_at")
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

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def output__pre(self, instance):
        return format_html("<pre>{}</pre>", escape(instance.output))

    def exportlog__pre(self, instance):
        value = json.dumps(instance.exportlog, indent=2, sort_keys=True)
        return format_html("<pre>{}</pre>", escape(value))

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
