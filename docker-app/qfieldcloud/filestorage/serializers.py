from datetime import timezone
from typing import cast

import drf_spectacular
from django.conf import settings
from rest_framework import serializers

from qfieldcloud.filestorage.models import (
    File,
    FileVersion,
)


@drf_spectacular.utils.extend_schema_serializer(
    deprecate_fields=(
        "last_modified",
        "sha256",
    )
)
class FileVersionSerializer(serializers.ModelSerializer):
    md5sum = serializers.SerializerMethodField()
    sha256 = serializers.SerializerMethodField()
    version_id = serializers.CharField(source="id")
    last_modified = serializers.DateTimeField(
        source="uploaded_at",
        format=settings.QFIELDCLOUD_STORAGE_DT_LAST_MODIFIED_FORMAT,
        default_timezone=timezone.utc,
    )
    is_latest = serializers.SerializerMethodField()

    def get_md5sum(self, obj: FileVersion) -> str:
        return obj.etag

    def get_sha256(self, obj: FileVersion) -> str:
        return obj.sha256sum.hex()

    def get_is_latest(self, obj: FileVersion) -> bool:
        return bool(obj.file.latest_version == obj)

    class Meta:
        model = FileVersion
        fields = (
            "version_id",
            "md5sum",
            "size",
            "uploaded_at",
            "display",
            "is_latest",
            # TODO delete the fields below, they are deprecated and exists only as a compatibility layer for the legacy storage
            "last_modified",
            "sha256",
        )

        read_only_fields = (
            "version_id",
            "md5sum",
            "size",
            "uploaded_at",
            "display",
            "is_latest",
            # TODO delete the fields below, they are deprecated and exists only as a compatibility layer for the legacy storage
            "last_modified",
            "sha256",
        )


@drf_spectacular.utils.extend_schema_serializer(
    deprecate_fields=(
        "last_modified",
        "sha256",
    )
)
class FileSerializer(serializers.ModelSerializer):
    size = serializers.SerializerMethodField()
    md5sum = serializers.SerializerMethodField()
    sha256 = serializers.SerializerMethodField()
    last_modified = serializers.DateTimeField(
        source="latest_version.uploaded_at",
        format=settings.QFIELDCLOUD_STORAGE_DT_LAST_MODIFIED_FORMAT,
        default_timezone=timezone.utc,
    )

    def get_md5sum(self, obj: File) -> str:
        return cast(FileVersion, obj.latest_version).etag

    def get_sha256(self, obj: File) -> str:
        return cast(FileVersion, obj.latest_version).sha256sum.hex()

    def get_size(self, obj: File) -> int:
        return cast(FileVersion, obj.latest_version).size

    class Meta:
        model = File
        fields = [
            "name",
            "size",
            "uploaded_at",
            "is_attachment",
            "md5sum",
            # TODO delete the fields below, they are deprecated and exists only as a compatibility layer for the legacy storage
            "last_modified",
            "sha256",
        ]
        read_only_fields = [
            "name",
            "size",
            "uploaded_at",
            "is_attachment",
            "md5sum",
            # TODO delete the fields below, they are deprecated and exists only as a compatibility layer for the legacy storage
            "last_modified",
            "sha256",
        ]
        order_by = "name"


class FileWithVersionsSerializer(FileSerializer):
    versions = FileVersionSerializer(many=True)

    class Meta(FileSerializer.Meta):
        fields = [*FileSerializer.Meta.fields, "versions"]
        read_only_fields = [*FileSerializer.Meta.read_only_fields, "versions"]
