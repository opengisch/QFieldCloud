from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from qfieldcloud.core.admin import QFieldCloudModelAdmin, qfc_admin_site

from .models import AuthToken

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
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        Here it is just the several available `AuthToken.ClientType`.
        """
        return AuthToken.ClientType.choices

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
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

    def expire_selected_tokens(self, request: HttpRequest, queryset: QuerySet) -> None:
        """
        Sets a set of tokens to expired by updating the `expires_at` date to now.
        Expires only valid tokens.
        """
        now = timezone.now()
        queryset.filter(Q(expires_at__gt=now)).update(expires_at=now)


qfc_admin_site.register(AuthToken, AuthTokenAdmin)
