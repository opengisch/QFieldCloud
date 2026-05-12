from typing import Any

from django.contrib import admin

from qfieldcloud.core.admin import QFieldCloudModelAdmin, qfc_admin_site
from qfieldcloud.filestorage.models import File, FileVersion


class FileAdmin(QFieldCloudModelAdmin):
    readonly_fields = [
        "id",
        "project",
        "package_job",
        "name",
        "file_type",
        "latest_version",
        "latest_version_count",
        "uploaded_at",
        "uploaded_by",
        "created_at",
    ]

    list_display = [
        "id",
        "project",
        "name",
        "latest_version",
        "latest_version_count",
        "uploaded_at",
        "uploaded_by",
    ]

    search_fields = (
        "name__istartswith",
        "latest_version__etag__istartswith",
        "uploaded_by__username__istartswith",
    )

    autocomplete_fields = ("latest_version",)

    ordering = ("-uploaded_at",)

    def has_add_permission(self, *_args: Any, **_kwargs: Any) -> bool:
        return False

    def has_change_permission(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


class FileVersionAdmin(QFieldCloudModelAdmin):
    readonly_fields = [
        "id",
        "file",
        "content",
        "file_storage",
        "md5sum_hex",
        "etag",
        "size",
        "uploaded_at",
        "uploaded_by",
    ]

    list_display = [
        "id",
        "file",
        "md5sum_hex",
        "etag",
        "size",
        "uploaded_at",
        "uploaded_by",
    ]

    search_fields = (
        "file__name__istartswith",
        "md5sum__icontains",
        "etag__istartswith",
        "uploaded_by__username__istartswith",
    )

    autocomplete_fields = ("file",)

    ordering = ("-uploaded_at",)

    def has_add_permission(self, *_args: Any, **_kwargs: Any) -> bool:
        # TODO @suricactus: Add the possibility to upload files via Django admin, see https://app.clickup.com/t/2192114/QF-8215
        return False

    def has_change_permission(self, *_args: Any, **_kwargs: Any) -> bool:
        return False

    @admin.display(description="MD5 HEX Checksum")
    def md5sum_hex(self, obj: FileVersion) -> str | None:
        return obj.md5sum.hex()


qfc_admin_site.register(File, FileAdmin)
qfc_admin_site.register(FileVersion, FileVersionAdmin)
