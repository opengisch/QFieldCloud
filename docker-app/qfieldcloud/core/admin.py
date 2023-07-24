import csv
import json
import time
from collections import namedtuple
from datetime import datetime
from itertools import chain
from typing import Any, Dict, Generator

from allauth.account.admin import EmailAddressAdmin as EmailAddressAdminBase
from allauth.account.forms import EmailAwarePasswordResetTokenGenerator
from allauth.account.models import EmailAddress
from allauth.account.utils import user_pk_to_url_str
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from auditlog.admin import LogEntryAdmin as BaseLogEntryAdmin
from auditlog.filters import ResourceTypeFilter
from auditlog.models import ContentType, LogEntry
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.db.models.fields.json import JSONField
from django.db.models.functions import Lower
from django.forms import ModelForm, fields, widgets
from django.http import HttpRequest
from django.http.response import Http404, HttpResponseRedirect, StreamingHttpResponse
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
from qfieldcloud.core.paginators import LargeTablePaginator
from qfieldcloud.core.templatetags.filters import filesizeformat10
from qfieldcloud.core.utils2 import jobs
from rest_framework.authtoken.models import TokenProxy

admin.site.unregister(LogEntry)

Invitation = get_invitation_model()


class NoPkOrderChangeList(ChangeList):
    """
    DjangoAdmin ChangeList adds an ordering -pk to ensure
    'deterministic ordering to all db backends'. This has a negative
    impact on performance and optimization.
    Therefore remove the extra ordering -pk if custom
    order fields are provided.
    """

    def get_ordering(self, request, queryset):
        order_fields = super().get_ordering(request, queryset)
        if len(order_fields) > 1 and "-pk" in order_fields:
            order_fields.remove("-pk")
        return order_fields


class ModelAdminNoPkOrderChangeListMixin:
    def get_changelist(self, request):
        return NoPkOrderChangeList


class ModelAdminEstimateCountMixin:
    # Avoid repetitive counting large list views.
    # Instead use pg metadata estimate.
    paginator = LargeTablePaginator

    # Display '(Show all)' instead of '(<count>)' in search bar
    show_full_result_count = False

    # Overwrite the default Django configuration of 100
    list_per_page = settings.QFIELDCLOUD_ADMIN_LIST_PER_PAGE


class QFieldCloudModelAdmin(
    ModelAdminNoPkOrderChangeListMixin, ModelAdminEstimateCountMixin, admin.ModelAdmin
):
    pass


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
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialApp)
admin.site.unregister(SocialToken)
admin.site.unregister(EmailAddress)

UserEmailDetails = namedtuple(
    "UserEmailDetails",
    [
        "id",
        "username",
        "first_name",
        "last_name",
        "type",
        "email",
        "date_joined",
        "last_login",
        "verified",
        "owner_id",
        "owner_username",
        "owner_email",
        "owner_first_name",
        "owner_last_name",
        "owner_date_joined",
        "owner_last_login",
    ],
)


class EmailAddressAdmin(EmailAddressAdminBase):
    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "admin/export_emails_to_csv/",
                self.admin_site.admin_view(self.export_emails_to_csv),
                name="export_emails_to_csv",
            ),
            *urls,
        ]

    def gen_users_email_addresses(self) -> Generator[UserEmailDetails, None, None]:
        raw_queryset = User.objects.raw(
            """
            WITH u AS (
                SELECT
                    DISTINCT ON (COALESCE(ae.email, u.email)) COALESCE(ae.email, u.email) AS "email",
                    u.id,
                    u.username,
                    u.first_name,
                    u.last_name,
                    u.type,
                    u.last_login,
                    u.date_joined
                FROM
                    core_user u
                    LEFT JOIN account_emailaddress ae ON ae.user_id = u.id AND ae.primary
                WHERE
                    COALESCE(ae.email, u.email) IS NOT NULL
                    AND COALESCE(ae.email, u.email) != ''
                ORDER BY
                    COALESCE(ae.email, u.email),
                    u.type
            )
            SELECT
                u.id,
                u.username,
                u.email,
                u.first_name,
                u.last_name,
                u.date_joined,
                u.last_login,
                u.type,
                ae.verified,
                oo.id AS "owner_id",
                oo.username AS "owner_username",
                oo.email AS "owner_email",
                oo.first_name AS "owner_first_name",
                oo.last_name AS "owner_last_name",
                oo.date_joined AS "owner_date_joined",
                oo.last_login AS "owner_last_login"
            FROM
                u
                LEFT JOIN account_emailaddress ae ON ae.user_id = u.id
                LEFT JOIN core_organization o ON o.user_ptr_id = u.id
                LEFT JOIN u oo ON oo.id = o.organization_owner_id
            ORDER BY u.id
            """
        )
        return (
            UserEmailDetails(
                row.id,
                row.username,
                row.first_name,
                row.last_name,
                row.type,
                row.email,
                row.date_joined,
                row.last_login,
                row.verified,
                row.owner_id,
                row.owner_username,
                row.owner_email,
                row.owner_first_name,
                row.owner_last_name,
                row.owner_date_joined,
                row.owner_last_login,
            )
            for row in raw_queryset
        )

    @admin.action(description="Export all users' email contact details to .csv")
    def export_emails_to_csv(self, request) -> StreamingHttpResponse:
        """ "Export all users' email contact details to .csv"""

        class PseudoBuffer:
            # Good idea from https://docs.djangoproject.com/en/4.1/howto/outputting-csv/
            def write(self, value):
                return value

        def human_readable_timestamp() -> str:
            d, h = str(datetime.utcnow()).split(" ")
            d = d.replace("-", "")
            h = h[:-7].replace(":", "")
            return "_".join([d, h])

        email_rows = self.gen_users_email_addresses()
        pseudo_buffer = PseudoBuffer()
        writer = csv.DictWriter(pseudo_buffer, fieldnames=UserEmailDetails._fields)
        header = {k: k for k in UserEmailDetails._fields}
        write_with_header = chain(
            [writer.writerow(header)],
            (writer.writerow(row._asdict()) for row in email_rows),
        )
        filename = f"qfc_user_email_{human_readable_timestamp()}"

        return StreamingHttpResponse(
            write_with_header,
            content_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
        )


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
        return obj is None

    def has_delete_permission(self, request, obj):
        return False


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


class PersonAdmin(QFieldCloudModelAdmin):
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
        # "storage_usage__field",
    )
    list_filter = (
        "type",
        "date_joined",
        "is_active",
        "is_staff",
    )

    search_fields = ("username__icontains", "email__iexact")

    fields = (
        "storage_usage__field",
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
        "groups",
        "remaining_invitations",
        "remaining_trial_organizations",
        "has_newsletter_subscription",
        "has_accepted_tos",
    )

    readonly_fields = (
        "date_joined",
        "last_login",
        "storage_usage__field",
    )

    inlines = (
        UserAccountInline,
        GeodbInline,
    )

    add_form_template = "admin/change_form.html"
    change_form_template = "admin/person_change_form.html"

    @admin.display(description=_("Storage"))
    def storage_usage__field(self, instance) -> str:
        active_storage_total = filesizeformat10(
            instance.useraccount.current_subscription.active_storage_total_bytes
        )
        used_storage = filesizeformat10(instance.useraccount.storage_used_bytes)
        used_storage_perc = instance.useraccount.storage_used_ratio * 100
        free_storage = filesizeformat10(instance.useraccount.storage_free_bytes)

        return _("total: {}; used: {} ({:.2f}%); free: {}").format(
            active_storage_total,
            used_storage,
            used_storage_perc,
            free_storage,
        )

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

    readonly_fields = (
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

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


class ProjectAdmin(QFieldCloudModelAdmin):
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
        "status",
        "status_code",
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
        "status",
        "status_code",
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

    def save_formset(self, request, form, formset, change):
        for form_obj in formset:
            if isinstance(form_obj.instance, ProjectCollaborator):
                # add created_by only if it's a newly created collaborator
                if form_obj.instance.id is None:
                    form_obj.instance.created_by = request.user

                form_obj.instance.updated_by = request.user

        super().save_formset(request, form, formset, change)


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


class IsFinalizedJobFilter(admin.SimpleListFilter):
    title = _("finalized job")
    parameter_name = "finalized"

    def lookups(self, request, model_admin):
        return (
            ("finalized", _("finalized")),
            ("not finalized", _("not finalized")),
        )

    def queryset(self, request, queryset) -> QuerySet:
        value = self.value()

        if value is None:
            return queryset

        not_finalized = (
            Q(status=Job.Status.PENDING)
            | Q(status=Job.Status.STARTED)
            | Q(status=Job.Status.QUEUED)
        )
        if value == "not finalized":
            return queryset.filter(not_finalized)
        elif value == "finalized":
            return queryset.filter(~not_finalized)
        else:
            raise NotImplementedError(
                f"Unknown filter: {value} (was expecting 'finalized' or 'not finalized')"
            )


class JobAdmin(QFieldCloudModelAdmin):
    list_display = (
        "id",
        "project__owner",
        "project__name",
        "type",
        "status",
        "error_type",
        "created_by__link",
        "created_at",
        "updated_at",
    )
    list_filter = ("type", "status", "updated_at", IsFinalizedJobFilter)
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
        "error_type",
        "type",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "docker_started_at",
        "docker_finished_at",
        "output__pre",
        "feedback__pre",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).defer("output", "feedback")

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

    def error_type(self, instance):
        if instance.feedback and "error_type" in instance.feedback:
            return f"{instance.feedback['error_type']}".strip()

        return None

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


class IsFinalizedDeltaJobFilter(admin.SimpleListFilter):
    title = _("finalized delta job")
    parameter_name = "finalized"

    def lookups(self, request, model_admin):
        return (
            ("finalized", _("finalized")),
            ("not finalized", _("not finalized")),
        )

    def queryset(self, request, queryset) -> QuerySet:
        value = self.value()

        if value is None:
            return queryset

        not_finalized = Q(last_status=Delta.Status.PENDING) | Q(
            last_status=Delta.Status.STARTED
        )

        if value == "not finalized":
            return queryset.filter(not_finalized)
        elif value == "finalized":
            return queryset.filter(~not_finalized)
        else:
            raise NotImplementedError(
                f"Unknown filter: {value} (was expecting 'finalized' or 'not finalized')"
            )


class DeltaAdmin(QFieldCloudModelAdmin):
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
    list_filter = ("last_status", "updated_at", IsFinalizedDeltaJobFilter)

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
        "old_geom_truncated",
        "new_geom_truncated",
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
        "old_geom_truncated",
        "new_geom_truncated",
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

    def old_geom_truncated(self, instance):
        return self.geom_truncated(instance.old_geom)

    def new_geom_truncated(self, instance):
        return self.geom_truncated(instance.new_geom)

    # Show geometries only truncated as they are fully shown in content
    def geom_truncated(self, geom):
        return f"{str(geom)[:70]} ..." if geom else "-"

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


class GeodbAdmin(QFieldCloudModelAdmin):
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
                f"The password is (shown only once): {obj.password}",
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


class OrganizationAdmin(QFieldCloudModelAdmin):
    inlines = (
        UserAccountInline,
        GeodbInline,
        OrganizationMemberInline,
        ProjectInline,
        TeamInline,
    )
    fields = (
        "storage_usage__field",
        "username",
        "email",
        "organization_owner",
        "date_joined",
        "active_users_links",
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
        "email__iexact",
        "organization_owner__email__iexact",
    )

    readonly_fields = (
        "date_joined",
        "storage_usage__field",
        "active_users_links",
    )

    list_select_related = ("organization_owner", "useraccount")

    list_filter = ("date_joined",)

    autocomplete_fields = ("organization_owner",)

    @admin.display(description=_("Active members"))
    def active_users_links(self, instance) -> str:
        persons = instance.useraccount.current_subscription.active_users
        userlinks = "<p> - </p>"
        if persons:
            userlinks = "<br>".join(model_admin_url(p, p.username) for p in persons)
        help_text = """
        <p style="font-size: 11px; color: var(--body-quiet-color)">
            Active members have triggererd at least one job or uploaded at least one delta in the current billing period.
            These are all the users who will be billed -- plan included or additional.
        </p>
        """
        return format_html(f"{userlinks} {help_text}")

    @admin.display(description=_("Owner"))
    def organization_owner__link(self, instance):
        return model_admin_url(
            instance.organization_owner, instance.organization_owner.username
        )

    @admin.display(description=_("Storage"))
    def storage_usage__field(self, instance) -> str:
        used_storage = filesizeformat10(instance.useraccount.storage_used_bytes)
        free_storage = filesizeformat10(instance.useraccount.storage_free_bytes)
        used_storage_perc = instance.useraccount.storage_used_ratio * 100
        return f"{used_storage} {free_storage} ({used_storage_perc:.2f}%)"

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


class TeamAdmin(QFieldCloudModelAdmin):
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


class UserAccountAdmin(QFieldCloudModelAdmin):
    """The sole purpose of this admin module is only to support autocomplete fields in Django admin."""

    ordering = (Lower("user__username"),)
    search_fields = ("user__username__icontains",)
    list_select_related = ("user",)

    def has_module_permission(self, request: HttpRequest) -> bool:
        # hide this module from Django admin, it is accessible via "Person" and "Organization" as inline edit
        return False


class UserAdmin(QFieldCloudModelAdmin):
    """The sole purpose of this admin module is only to support autocomplete fields in Django admin."""

    ordering = (Lower("username"),)
    search_fields = ("username__icontains",)

    def has_module_permission(self, request: HttpRequest) -> bool:
        # hide this module from Django admin, it is accessible via "Person" and "Organization" as inline edit
        return False


class QFieldCloudResourceTypeFilter(ResourceTypeFilter):
    def lookups(self, request, model_admin):
        qs = ContentType.objects.all().order_by("model")
        types = qs.values_list("id", "model")
        return types


class LogEntryAdmin(
    ModelAdminNoPkOrderChangeListMixin, ModelAdminEstimateCountMixin, BaseLogEntryAdmin
):
    list_filter = ("action", QFieldCloudResourceTypeFilter)


admin.site.register(Invitation, InvitationAdmin)
admin.site.register(Person, PersonAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Delta, DeltaAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(Geodb, GeodbAdmin)
admin.site.register(LogEntry, LogEntryAdmin)

# The sole purpose of the `User` and `UserAccount` admin modules is only to support autocomplete fields in Django admin
admin.site.register(User, UserAdmin)
admin.site.register(UserAccount, UserAccountAdmin)
admin.site.register(EmailAddress, EmailAddressAdmin)
