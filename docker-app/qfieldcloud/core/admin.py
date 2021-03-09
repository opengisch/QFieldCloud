from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin, messages
from django.contrib.auth.models import Group
from qfieldcloud.core.models import (
    Delta,
    Geodb,
    Organization,
    OrganizationMember,
    Project,
    ProjectCollaborator,
    User,
    UserAccount,
)


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
admin.site.register(UserAccount, UserAccountAdmin)
admin.site.register(Geodb, GeodbAdmin)

admin.site.register(Organization)
admin.site.register(OrganizationMember)
admin.site.register(ProjectCollaborator)

admin.site.unregister(Group)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
