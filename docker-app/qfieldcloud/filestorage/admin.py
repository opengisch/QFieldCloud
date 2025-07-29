from django.contrib import admin

from qfieldcloud.core.admin import qfc_admin_site

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


qfc_admin_site.register(File, FileAdmin)
qfc_admin_site.register(FileVersion, FileVersionAdmin)
