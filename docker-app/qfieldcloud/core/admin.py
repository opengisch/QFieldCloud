import json
import time

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin, messages
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.auth.models import Group
from django.db.models.fields.json import JSONField
from django.forms import widgets
from django.http.response import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.utils.html import escape, format_html
from django.utils.safestring import SafeText
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    Geodb,
    Organization,
    OrganizationMember,
    PackageJob,
    ProcessProjectfileJob,
    Project,
    ProjectCollaborator,
    Team,
    TeamMember,
    User,
    UserAccount,
)
from qfieldcloud.core.utils2 import jobs


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


class GeodbInline(admin.TabularInline):
    model = Geodb
    extra = 0

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


class OwnedOrganizationInline(admin.TabularInline):
    model = Organization
    fk_name = "organization_owner"
    extra = 0

    fields = (
        "owned_organization",
        "email",
    )
    readonly_fields = (
        "owned_organization",
        "email",
    )

    def owned_organization(self, obj):
        return model_admin_url(obj, obj.username)

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


class MemberOrganizationInline(admin.TabularInline):
    model = OrganizationMember
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)


class MemberTeamInline(admin.TabularInline):
    model = TeamMember
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)


class UserAccountInline(admin.StackedInline):
    model = UserAccount
    extra = 1

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type in (User.TYPE_USER, User.TYPE_ORGANIZATION)


class ProjectInline(admin.TabularInline):
    model = Project
    extra = 0

    fields = ("owned_project", "is_public", "overwrite_conflicts")
    readonly_fields = ("owned_project",)

    def owned_project(self, obj):
        return model_admin_url(obj, obj.name)

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


class UserProjectCollaboratorInline(admin.TabularInline):
    model = ProjectCollaborator
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type == User.TYPE_USER

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type == User.TYPE_USER

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.user_type == User.TYPE_USER


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
    list_filter = (
        "user_type",
        "date_joined",
        "is_active",
        "is_staff",
        "useraccount__account_type",
    )

    search_fields = ("username__icontains", "owner__username__iexact")

    fields = (
        "username",
        "password",
        "email",
        "first_name",
        "last_name",
        "remaining_invitations",
        "date_joined",
        "last_login",
        "is_superuser",
        "is_staff",
        "is_active",
        "has_newsletter_subscription",
        "has_accepted_tos",
    )

    inlines = (
        UserAccountInline,
        GeodbInline,
        OwnedOrganizationInline,
        MemberOrganizationInline,
        MemberTeamInline,
        ProjectInline,
        UserProjectCollaboratorInline,
    )

    def save_model(self, request, obj, form, change):
        # Set the password to the value in the field if it's changed.
        if obj.pk:
            if "password" in form.changed_data:
                obj.set_password(obj.password)
        else:
            obj.set_password(obj.password)
        obj.save()


class ProjectCollaboratorInline(admin.TabularInline):
    model = ProjectCollaborator
    extra = 0


class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "owner",
        "is_public",
        "description",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_public",
        "created_at",
        "updated_at",
    )
    fields = (
        "id",
        "name",
        "description",
        "is_public",
        "owner",
        "storage_size_mb",
        "created_at",
        "updated_at",
        "data_last_updated_at",
        "data_last_packaged_at",
        "project_details__pre",
    )
    readonly_fields = (
        "id",
        "storage_size_mb",
        "created_at",
        "updated_at",
        "data_last_updated_at",
        "data_last_packaged_at",
        "project_details__pre",
    )
    inlines = (ProjectCollaboratorInline,)
    search_fields = (
        "id",
        "name__icontains",
        "owner__username__iexact",
    )

    def project_details__pre(self, instance):
        if instance.project_details is None:
            return ""

        return format_pre_json(instance.project_details)


class DeltaInline(admin.TabularInline):
    model = ApplyJob.deltas_to_apply.through

    fields = (
        "delta",
        "status",
        # TODO find a way to use dynamic fields
        # "feedback__pre",
    )

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    # def feedback__pre(self, instance):
    #     return format_pre_json(instance.feedback)


class ApplyJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )

    list_filter = ("status", "updated_at")
    ordering = ("-updated_at",)
    search_fields = (
        "project__name__iexact",
        "project__owner__username__iexact",
        "deltas_to_apply__id__startswith",
        "id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    )
    inlines = [
        DeltaInline,
    ]

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ApplyJobDeltaInline(admin.TabularInline):
    model = ApplyJobDelta

    readonly_fields = (
        "job_id",
        "status",
        "output__pre",
    )

    fields = (
        "job_id",
        "status",
        "output__pre",
    )

    def job_id(self, instance):
        return model_admin_url(instance.apply_job)

    def output__pre(self, instance):
        return format_pre_json(instance.output)

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False


class DeltaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deltafile_id",
        "project__owner",
        "project__name",
        "last_status",
        "created_by",
        "created_at",
        "updated_at",
    )
    list_filter = ("last_status", "updated_at")

    actions = (
        "set_status_pending",
        "set_status_ignored",
        "set_status_unpermitted",
        "apply_selected_deltas",
    )

    readonly_fields = (
        "project",
        "deltafile_id",
        "last_feedback__pre",
        "last_modified_pk",
        "created_by",
        "created_at",
        "updated_at",
    )
    fields = (
        "project",
        "deltafile_id",
        "last_status",
        "created_by",
        "created_at",
        "updated_at",
        "content",
        "last_feedback__pre",
        "last_modified_pk",
    )
    search_fields = (
        "project__name__iexact",
        "project__owner__username__iexact",
        "last_feedback__icontains",
        "deltafile_id__startswith",
        "id",
    )
    ordering = ("-updated_at",)

    inlines = [
        ApplyJobDeltaInline,
    ]

    formfield_overrides = {JSONField: {"widget": PrettyJSONWidget}}

    change_form_template = "admin/delta_change_form.html"

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    def last_feedback__pre(self, instance):
        return format_pre_json(instance.last_feedback)

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def set_status_pending(self, request, queryset):
        queryset.update(last_status=Delta.Status.PENDING)

    def set_status_ignored(self, request, queryset):
        queryset.update(last_status=Delta.Status.IGNORED)

    def set_status_unpermitted(self, request, queryset):
        queryset.update(last_status=Delta.Status.UNPERMITTED)

    def response_change(self, request, delta):
        if "_apply_delta_btn" in request.POST:
            if not delta.project.project_filename:
                self.message_user(request, "Missing project file")
                raise exceptions.NoQGISProjectError()

            if not jobs.apply_deltas(
                delta.project,
                request.user,
                delta.project.project_filename,
                delta.project.overwrite_conflicts,
                delta_ids=[str(delta.id)],
            ):
                self.message_user(request, "No deltas to apply")
                raise exceptions.NoDeltasToApplyError()

            self.message_user(request, "Delta application started")

            # we need to sleep 1 second, just to make sure the apply delta started
            time.sleep(1)

            return HttpResponseRedirect(".")

        return super().response_change(request, delta)


class PackageJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "updated_at")
    list_select_related = ("project", "project__owner")
    actions = None
    exclude = ("feedback", "output")

    readonly_fields = (
        "project",
        "status",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "output__pre",
        "feedback__pre",
    )

    search_fields = (
        "id",
        "feedback__icontains",
        "project__name__iexact",
        "project__owner__username__iexact",
    )

    ordering = ("-updated_at",)

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def output__pre(self, instance):
        return format_pre(instance.output)

    def feedback__pre(self, instance):
        return format_pre_json(instance.feedback)

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ProcessProjectfileJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "status",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "updated_at")
    list_select_related = ("project", "project__owner")
    actions = None
    exclude = ("feedback", "output")

    readonly_fields = (
        "project",
        "status",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "output__pre",
        "feedback__pre",
    )

    search_fields = (
        "id",
        "feedback__icontains",
        "project__name__iexact",
        "project__owner__username__iexact",
    )

    ordering = ("-updated_at",)

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def output__pre(self, instance):
        return format_pre(instance.output)

    def feedback__pre(self, instance):
        return format_pre_json(instance.feedback)

    # This will disable add functionality
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class GeodbAdmin(admin.ModelAdmin):
    list_filter = ("created_at", "hostname")
    list_display = (
        "user",
        "username",
        "dbname",
        "hostname",
        "port",
        "created_at",
        "size",
    )

    fields = (
        "user",
        "username",
        "dbname",
        "hostname",
        "port",
        "created_at",
        "size",
        "last_geodb_error",
    )

    readonly_fields = ("size", "created_at", "last_geodb_error")

    search_fields = (
        "user__username",
        "username",
        "dbname",
        "hostname",
    )

    def save_model(self, request, obj, form, change):
        # Only on creation
        if not change:
            messages.add_message(
                request,
                messages.WARNING,
                "The password is (shown only once): {}".format(obj.password),
            )
        super().save_model(request, obj, form, change)


class OrganizationMemberInline(admin.TabularInline):
    model = OrganizationMember
    fk_name = "organization"
    extra = 0


class TeamInline(admin.TabularInline):
    model = Team
    fk_name = "team_organization"
    extra = 0

    fields = ("username",)

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


class OrganizationAdmin(admin.ModelAdmin):
    inlines = (
        UserAccountInline,
        GeodbInline,
        OrganizationMemberInline,
        ProjectInline,
        TeamInline,
    )
    fields = (
        "username",
        "email",
        "organization_owner",
    )
    list_display = (
        "username",
        "email",
        "organization_owner__link",
        "date_joined",
        "useraccount",
    )

    search_fields = (
        "username__icontains",
        "owner__username__icontains",
    )

    list_filter = ("date_joined",)

    def organization_owner__link(self, instance):
        return model_admin_url(
            instance.organization_owner, instance.organization_owner.username
        )


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    fk_name = "team"
    extra = 0


class TeamAdmin(admin.ModelAdmin):
    inlines = (TeamMemberInline,)

    list_display = (
        "username",
        "date_joined",
    )

    fields = (
        "username",
        "team_organization",
    )

    search_fields = ("username__icontains", "team_organization__username__iexact")

    list_filter = ("date_joined",)

    def save_model(self, request, obj, form, change):
        if not obj.username.startswith("@"):
            obj.username = f"@{obj.team_organization.username}/{obj.username}"
        obj.save()


admin.site.register(User, UserAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Delta, DeltaAdmin)
admin.site.register(ApplyJob, ApplyJobAdmin)
admin.site.register(PackageJob, PackageJobAdmin)
admin.site.register(ProcessProjectfileJob, ProcessProjectfileJobAdmin)
admin.site.register(Geodb, GeodbAdmin)

admin.site.unregister(Group)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
