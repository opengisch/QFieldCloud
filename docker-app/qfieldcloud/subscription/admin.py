from django.contrib import admin
from django.contrib.admin import register

from .models import PackageType, Plan


@register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_default",
        "is_public",
        "display_name",
        "storage_mb",
        "job_minutes",
    ]


@register(PackageType)
class PackageTypeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "is_public",
        "display_name",
        "type",
        "unit_amount",
        "unit_label",
    ]
