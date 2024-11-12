from django.contrib import admin
from django.contrib.admin import register
from django.db.models import Q, QuerySet

from .models import AuthToken


class AuthTokenClientTypeFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # admin page in the filter options
    title = "Client type"

    # Parameter for the filter that will be used in the URL query.
    parameter_name = "client_type"

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        Here it is just the several available AuthToken.ClientType
        """
        return AuthToken.ClientType.choices

    def queryset(self, request, queryset) -> QuerySet:
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


@register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
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

    search_fields = ("user__username__iexact", "client_type", "key__startswith")
