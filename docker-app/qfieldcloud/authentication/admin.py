from django.contrib import admin
from django.contrib.admin import register

from .models import AuthToken


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
    list_filter = ("created_at", "last_used_at", "expires_at")

    search_fields = ("user__username__iexact", "client_type", "key__startswith")
