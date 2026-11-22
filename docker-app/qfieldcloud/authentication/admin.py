from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.admin import QFieldCloudModelAdmin, qfc_admin_site
from qfieldcloud.core.admin_dashboards.active_users import (
    get_active_users_by_client_card,
)
from qfieldcloud.core.admin_dashboards.utils import DASHBOARD_PERIODS, get_period

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise
else:
    StrOrPromise = str


class AuthTokenClientTypeFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed
    title = "Client type"

    # Parameter for the filter that will be used in the URL query.
    parameter_name = "client_type"

    def lookups(
        self, request: HttpRequest, model_admin: admin.ModelAdmin
    ) -> list[tuple[str, StrOrPromise]]:
        """Returns a list of tuples for choices.

        The first element in each tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.

        Here it is just the several available `AuthToken.ClientType`.
        """
        return AuthToken.ClientType.choices

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        """Returns the filtered queryset based on the value  provided in the query string and retrievable via `self.value()`."""
        value = self.value()

        if value is None:
            return queryset

        accepted_values = [ct[0] for ct in AuthToken.ClientType.choices]
        if value not in accepted_values:
            raise NotImplementedError(
                f"Unknown client type: {value} (was expecting: {','.join(accepted_values)})"
            )

        return queryset.filter(Q(client_type=value))


class AuthTokenAdmin(QFieldCloudModelAdmin):
    list_display = ("user", "created_at", "expires_at", "last_used_at", "client_type")
    readonly_fields = (
        "key",
        "user",
        "created_at",
        "last_used_at",
        "client_type",
        "user_agent",
    )
    list_filter = (
        "created_at",
        "last_used_at",
        "expires_at",
        AuthTokenClientTypeFilter,
    )

    actions = ("expire_selected_tokens",)

    search_fields = ("user__username__iexact", "client_type", "key__startswith")

    list_before_template = "admin/authentication/authtoken/active_users.html"

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        """Shows the auth tokens list, with the active users card of the period in the `period` parameter above it."""
        period = get_period(request.GET)

        # `period` is not a field of the tokens, the changelist would reject it as a filter
        query_dict = request.GET.copy()
        query_dict.pop("period", None)
        request.GET = query_dict  # type: ignore[assignment]

        if extra_context is None:
            extra_context = {}

        extra_context["active_users_card"] = get_active_users_by_client_card(period)
        extra_context["dashboard_period"] = period
        extra_context["dashboard_period_title"] = DASHBOARD_PERIODS[period]["title"]
        extra_context["dashboard_periods"] = DASHBOARD_PERIODS

        return super().changelist_view(request, extra_context)

    def expire_selected_tokens(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Sets a set of tokens to expired by updating the `expires_at` date to now. Expires only valid tokens."""
        now = timezone.now()
        queryset.filter(Q(expires_at__gt=now)).update(expires_at=now)


qfc_admin_site.register(AuthToken, AuthTokenAdmin)
