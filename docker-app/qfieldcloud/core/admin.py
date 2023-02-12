import json
import time
from typing import Any, Dict

from allauth.account.forms import EmailAwarePasswordResetTokenGenerator
from allauth.account.utils import user_pk_to_url_str
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models.fields.json import JSONField
from django.db.models.functions import Lower
from django.forms import ModelForm, fields, widgets
from django.http import HttpRequest
from django.http.response import Http404, HttpResponseRedirect
from django.shortcuts import resolve_url
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import escape, format_html
from django.utils.safestring import SafeText
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from invitations.admin import InvitationAdmin as InvitationAdminBase
from invitations.utils import get_invitation_model
from qfieldcloud.core import exceptions
from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    Geodb,
    Job,
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Team,
    TeamMember,
    User,
    UserAccount,
)
from qfieldcloud.core.utils2 import jobs
from rest_framework.authtoken.models import TokenProxy

Invitation = get_invitation_model()


def admin_urlname_by_obj(value, arg):
    if isinstance(value, User):
        if value.is_person:
            return "admin:core_person_%s" % (arg)
        elif value.is_organization:
            return "admin:core_organization_%s" % (arg)
        elif value.is_team:
            return "admin:core_team_%s" % (arg)
        else:
            raise NotImplementedError("Unknown user type!")
    elif isinstance(value, Job):
        return "admin:core_job_%s" % (arg)
    else:
        return admin_urlname(value._meta, arg)


# Unregister admins from other Django apps
admin.site.unregister(Invitation)
admin.site.unregister(TokenProxy)
admin.site.unregister(Group)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)


class PrettyJSONWidget(widgets.Textarea):
    def format_value(self, value):
        text_value = json.dumps(json.loads(value), indent=2, sort_keys=True)

        row_lengths = [len(r) for r in text_value.split("\n")]

        self.attrs["rows"] = min(max(len(row_lengths) + 2, 10), 30)
        self.attrs["cols"] = min(max(max(row_lengths) + 2, 40), 120)
        return SafeText(text_value)


def search_parser(
    _request, _queryset, search_term: str, filter_config: Dict[str, Dict[str, str]]
) -> Dict[str, Any]:
    custom_filter = {}
    CUSTOM_SEARCH_DIVIDER = ":"
    if CUSTOM_SEARCH_DIVIDER in search_term:
        prefix, search = search_term.split(CUSTOM_SEARCH_DIVIDER, 1)
        prefix_config = filter_config.get(prefix)
        if prefix_config:
            extra_filters = prefix_config.get("extra_filters", {})
            filter_keyword = prefix_config["filter"]

            custom_filter = {**custom_filter, **extra_filters}
            custom_filter[filter_keyword] = search

    return custom_filter


def model_admin_url(obj, name: str = None) -> str:
    url = resolve_url(admin_urlname_by_obj(obj, SafeText("change")), obj.pk)
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


class MemberOrganizationInline(admin.TabularInline):
    model = OrganizationMember
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)


class MemberTeamInline(admin.TabularInline):
    model = TeamMember
    extra = 0

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)


class UserAccountInline(admin.StackedInline):
    model = UserAccount
    extra = 1

    def has_add_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type in (User.Type.PERSON, User.Type.ORGANIZATION)


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
        return obj.type == User.Type.PERSON

    def has_delete_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type == User.Type.PERSON

    def has_change_permission(self, request, obj):
        if obj is None:
            return True
        return obj.type == User.Type.PERSON


class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "is_superuser",
        "is_staff",
        "is_active",
        "date_joined",
        "last_login",
    )
    list_filter = (
        "type",
        "date_joined",
        "is_active",
        "is_staff",
    )

    search_fields = ("username__icontains",)

    fields = (
        "username",
        "password",
        "email",
        "first_name",
        "last_name",
        "date_joined",
        "last_login",
        "is_superuser",
        "is_staff",
        "is_active",
        "remaining_invitations",
        "has_newsletter_subscription",
        "has_accepted_tos",
    )

    inlines = (
        UserAccountInline,
        GeodbInline,
    )

    add_form_template = "admin/change_form.html"
    change_form_template = "admin/person_change_form.html"

    def save_model(self, request, obj, form, change):
        # Set the password to the value in the field if it's changed.
        if obj.pk:
            if "password" in form.changed_data:
                obj.set_password(obj.password)
        else:
            obj.set_password(obj.password)
        obj.save()

    def get_urls(self):
        urls = super().get_urls()

        urls = [
            *urls,
            path(
                "<int:user_id>/password_reset_url",
                self.admin_site.admin_view(self.password_reset_url),
                name="password_reset_url",
            ),
        ]
        return urls

    @method_decorator(never_cache)
    def password_reset_url(self, request, user_id, form_url=""):
        if not self.has_change_permission(request):
            raise PermissionDenied

        user = self.get_object(request, user_id)
        if user is None:
            raise Http404(
                _("%(name)s object with primary key %(key)r does " "not exist.")
                % {
                    "name": self.model._meta.verbose_name,
                    "key": escape(user_id),
                }
            )

        token_generator = EmailAwarePasswordResetTokenGenerator()
        url = reverse(
            "account_reset_password_from_key",
            kwargs={
                "uidb36": user_pk_to_url_str(user),
                "key": token_generator.make_token(user),
            },
        )
        return TemplateResponse(
            request,
            "admin/password_reset_url.html",
            context={
                "user": user,
                "url": request.build_absolute_uri(url),
                "title": _("Password reset"),
                "timeout_days": settings.PASSWORD_RESET_TIMEOUT / 3600 / 24,
            },
        )


class ProjectCollaboratorInline(admin.TabularInline):
    model = ProjectCollaborator
    extra = 0

    autocomplete_fields = ("collaborator",)


class ProjectFilesWidget(widgets.Input):
    template_name = "admin/project_files_widget.html"


class ProjectForm(ModelForm):
    project_files = fields.CharField(
        disabled=True, required=False, widget=ProjectFilesWidget
    )

    class Meta:
        model = Project
        widgets = {"project_filename": widgets.TextInput()}
        fields = "__all__"  # required for Django 3.x


class ProjectAdmin(admin.ModelAdmin):
    form = ProjectForm
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
        "project_filename",
        "file_storage_bytes",
        "created_at",
        "updated_at",
        "data_last_updated_at",
        "data_last_packaged_at",
        "project_details__pre",
        "project_files",
    )
    readonly_fields = (
        "id",
        "file_storage_bytes",
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
    autocomplete_fields = ("owner",)

    ordering = ("-updated_at",)

    def get_search_results(self, request, queryset, search_term):
        filters = search_parser(
            request,
            queryset,
            search_term,
            {
                "owner": {
                    "filter": "owner__username__iexact",
                },
                "collaborator": {
                    "filter": "user_roles__user__username__iexact",
                    "extra_filters": {
                        "is_public": False,
                    },
                },
            },
        )

        if filters:
            return queryset.filter(**filters), True

        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )

        return queryset, use_distinct

    def project_files(self, instance):
        return instance.pk

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


class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "type",
        "status",
        "created_by__link",
        "created_at",
        "updated_at",
    )
    list_filter = ("type", "status", "updated_at")
    list_select_related = ("project", "project__owner", "created_by")
    exclude = ("feedback", "output")
    ordering = ("-updated_at",)
    search_fields = (
        "project__name__iexact",
        "project__owner__username__iexact",
        "id",
    )
    readonly_fields = (
        "project",
        "status",
        "type",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "output__pre",
        "feedback__pre",
    )

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj and obj.type == Job.Type.DELTA_APPLY:
            obj = ApplyJob.objects.get(pk=obj.pk)
        return obj

    def get_inline_instances(self, request, obj=None):
        inline_instances = super().get_inline_instances(request, obj)

        if isinstance(obj, ApplyJob):
            for inline_instance in inline_instances:
                if inline_instance.parent_model == Job:
                    inline_instance.parent_model = ApplyJob

        return inline_instances

    def get_inlines(self, request, obj=None):
        inlines = [*super().get_inlines(request, obj)]

        if obj and obj.type == Job.Type.DELTA_APPLY:
            inlines.append(DeltaInline)

        return inlines

    def project__owner(self, instance):
        return model_admin_url(instance.project.owner)

    project__owner.admin_order_field = "project__owner"

    def project__name(self, instance):
        return model_admin_url(instance.project, instance.project.name)

    project__name.admin_order_field = "project__name"

    def created_by__link(self, instance):
        return model_admin_url(instance.created_by)

    created_by__link.admin_order_field = "created_by"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def output__pre(self, instance):
        return format_pre(instance.output)

    def feedback__pre(self, instance):
        return format_pre_json(instance.feedback)


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

    autocomplete_fields = ("member",)


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
    )

    search_fields = (
        "username__icontains",
        "organization_owner__username__icontains",
    )

    list_select_related = ("organization_owner",)

    list_filter = ("date_joined",)

    autocomplete_fields = ("organization_owner",)

    def organization_owner__link(self, instance):
        return model_admin_url(
            instance.organization_owner, instance.organization_owner.username
        )

    def get_search_results(self, request, queryset, search_term):
        filters = search_parser(
            request,
            queryset,
            search_term,
            {
                "owner": {
                    "filter": "organization_owner__username__iexact",
                },
                "member": {
                    "filter": "membership_roles__user__username__iexact",
                },
            },
        )

        if filters:
            return queryset.filter(**filters), True

        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )

        return queryset, use_distinct


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    fk_name = "team"
    extra = 0

    autocomplete_fields = ("member",)


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

    autocomplete_fields = ("team_organization",)

    def save_model(self, request, obj, form, change):
        if not obj.username.startswith("@"):
            obj.username = f"@{obj.team_organization.username}/{obj.username}"
        obj.save()


class InvitationAdmin(InvitationAdminBase):
    list_display = ("email", "inviter", "created", "sent", "accepted")
    list_select_related = ("inviter",)
    list_filter = (
        "accepted",
        "created",
        "sent",
    )
    search_fields = ("email__icontains", "inviter__username__iexact")


class UserAccountAdmin(admin.ModelAdmin):
    """The sole purpose of this admin module is only to support autocomplete fields in Django admin."""

    ordering = (Lower("user__username"),)
    search_fields = ("user__username__icontains",)
    list_select_related = ("user",)

    def has_module_permission(self, request: HttpRequest) -> bool:
        # hide this module from Django admin, it is accessible via "Person" and "Organization" as inline edit
        return False


class UserAdmin(admin.ModelAdmin):
    """The sole purpose of this admin module is only to support autocomplete fields in Django admin."""

    ordering = (Lower("username"),)
    search_fields = ("username__icontains",)

    def get_queryset(self, request: HttpRequest):
        return (
            super()
            .get_queryset(request)
            .filter(type__in=(User.Type.PERSON, User.Type.ORGANIZATION))
        )

    def has_module_permission(self, request: HttpRequest) -> bool:
        # hide this module from Django admin, it is accessible via "Person" and "Organization" as inline edit
        return False


admin.site.register(Invitation, InvitationAdmin)
admin.site.register(Person, PersonAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Delta, DeltaAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(Geodb, GeodbAdmin)

# The sole purpose of the `User` and `UserAccount` admin modules is only to support autocomplete fields in Django admin
admin.site.register(User, UserAdmin)
admin.site.register(UserAccount, UserAccountAdmin)
