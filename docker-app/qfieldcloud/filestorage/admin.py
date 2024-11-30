from django.contrib import admin

from .models import File, FileVersion


class FileAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "project",
        "name",
        "latest_version",
        "latest_version_count",
        "uploaded_at",
        "uploaded_by",
    ]

    list_display_links = [
        "project",
        "latest_version",
        "uploaded_by",
    ]


class FileVersionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "file",
        "md5sum",
        "size",
        "uploaded_at",
        "uploaded_by",
    ]
    list_display_links = [
        "file",
        "uploaded_by",
    ]


admin.site.register(File, FileAdmin)
admin.site.register(FileVersion, FileVersionAdmin)
