from django.contrib import admin
from django.contrib.admin import register

from .models import AccountType, ExtraPackageTypeJobMinutes, ExtraPackageTypeStorage


@register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_default",
        "is_public",
        "display_name",
        "storage_mb",
        "job_minutes",
    ]


@register(ExtraPackageTypeStorage, ExtraPackageTypeJobMinutes)
class ExtraPackageTypeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_public",
        "display_name",
    ]
