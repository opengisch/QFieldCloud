from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import OuterRef, F, Sum, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _
from django.core.files.base import ContentFile
from django.core.validators import (
    MaxLengthValidator,
    MinLengthValidator,
    ProhibitNullCharactersValidator,
)

from qfieldcloud.core.models import Job, Project, User
from qfieldcloud.core.utils2 import storage
from qfieldcloud.core.fields import DynamicStorageFileField
from qfieldcloud.core.validators import MaxBytesLengthValidator
from .utils import calc_etag, filename_validator


class FileQueryset(models.QuerySet):
    def whatever(self):
        qs = self.annotate(
            last_version_pk=(
                FileVersion.objects.filter(file=OuterRef("pk"))
                .order_by("-uploaded_at")
                .values("pk")[:1]
            )
        )
        qs = qs.prefetch_related("versions")
        return qs

    def get_by_name(self, filename: str):
        return self.get(name=filename)


class File(models.Model):
    versions: QuerySet[FileVersion]

    class FileType(models.IntegerChoices):
        """The type of file, or in other words the context file shall be used."""

        # project files are regular project files
        PROJECT_FILE = (1, _("Project File"))

        # package files are project files prepared for downloading to QField, e.g. offlined databases
        PACKAGE_FILE = (2, _("Package File"))

    objects = FileQueryset.as_manager()

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        editable=False,
        related_name="files",
    )
    # organization_id = models.ForeignKey(Organization, on_delete=models.CASCADE, editable=False)

    package_job_id: int
    package_job = models.ForeignKey(
        Job,
        on_delete=models.DO_NOTHING,
        editable=False,
        null=True,
        limit_choices_to=models.Q(type=Job.Type.PACKAGE),
    )

    name = models.CharField(
        db_index=True,
        max_length=settings.STORAGE_FILENAME_MAX_CHAR_LENGTH,
        validators=(
            # Require at least 1 character filenames
            MinLengthValidator(1),
            # NOTE the files on Windows cannot be longer than 260 _chars_ by default, see https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file?redirectedfrom=MSDN#maximum-path-length-limitation
            # NOTE minio limit is 255 _chars_ per filename segment, read https://min.io/docs/minio/linux/operations/concepts/thresholds.html#id1
            MaxLengthValidator(settings.STORAGE_FILENAME_MAX_CHAR_LENGTH),
            # NOTE the keys on S3 cannot be longer than 1024 _bytes_, see https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
            MaxBytesLengthValidator(1024),
            # Make sure no null characters get into the name
            ProhibitNullCharactersValidator(),
            # Use the filename regex validator that is used also on all clients
            filename_validator,
        ),
    )

    # The type of the stored file. The type is assigned once at creation time and cannot be changed.
    file_type = models.PositiveSmallIntegerField(
        choices=FileType.choices,
        editable=False,
    )

    latest_version_id: int
    latest_version = models.ForeignKey(
        "filestorage.FileVersion",
        null=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

    latest_version_count = models.PositiveIntegerField(default=0)

    uploaded_at = models.DateTimeField(default=timezone.now, editable=False)

    # Timestamp when the file has been deleted. Null if the file is not deleted.
    # TODO enable `deleted_at` to keep the deleted files in the project history
    # deleted_at = models.DateTimeField(null=True, blank=True)

    # # User who deleted the file.
    # TODO enable `deleted_by` to keep the deleted files in the project history
    # deleted_by = models.ForeignKey(User, on_delete=models.DO_NOTHING, null=True, blank=True)

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        editable=False,
        null=True,
    )

    # Timestamp when the `FileVersion` record was inserted in the database.
    # TODO We do not `auto_now_add=True` to be able to set this when migrating files from legacy to the regular storage. Switch to `auto_now_add=True` when the legacy storage is no longer supported.
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def is_attachment(self):
        return storage.get_attachment_dir_prefix(self.project, self.name) != ""

    def remove_version(self, version_id):
        self.versions.get(version_id).delete

    def get_total_versions_size(self) -> int:
        return self.versions.aggregate(size=Sum("size", default=0))["size"]

    def __repr__(self) -> str:
        return f'File({self.pk}) in "{self.project_id}" "{self.name}"'  # type: ignore

    def __str__(self) -> str:
        return self.__repr__()


class FileVersionQueryset(models.QuerySet):
    @transaction.atomic()
    def add_version(
        self,
        project: Project,
        filename: str,
        content: ContentFile,
        file_type: File.FileType,
        uploaded_by: User,
        uploaded_at: datetime | None = None,
        created_at: datetime | None = None,
        version_id: UUID | None = None,
        package_job_id: UUID | None = None,
    ) -> FileVersion:
        """Adds a new file version with specific filename.

        If the `File` object does not exist, this method will create it.

        This method runs in a transaction. It creates/updates a `File` object and creates a new `FileVersion` object.

        Args:
            project (Project): the project the file belongs to
            filename (str): the filename
            content (ContentFile): the file content
            file_type (File.FileType): the file type
            uploaded_by (User): the `User` that uploaded the file
            uploaded_at (datetime | None, optional): the timestamp when the file has been uploaded. When `None`, the value is set to the current timestamp. Defaults to None.
            created_at (datetime | None, optional): the timestamp when the file has been created. When `None`, the value is set to the current timestamp. Defaults to None.
            version_id (UUID | None, optional): The uuid to be used assigned to that version. When `None`, the value is a new random UUID4. This argument is used to move from legacy versioned object storage to the new `django-storages` version. Defaults to None.
            package_job_id (UUID | None, optional): The package job the file belongs to. Defaults to None.

        Returns:
            FileVersion: the file version that has been created
        """
        now = timezone.now()

        if not uploaded_at:
            uploaded_at = now

        if not created_at:
            created_at = now

        if not version_id:
            version_id = uuid4()

        try:
            file = File.objects.get(
                project_id=project.id,
                name=filename,
                file_type=file_type,
                package_job_id=package_job_id,
            )
        except File.DoesNotExist:
            file = File.objects.create(
                project_id=project.id,
                name=filename,
                file_type=file_type,
                uploaded_by=uploaded_by,
                uploaded_at=uploaded_at,
                created_at=created_at,
                package_job_id=package_job_id,
                latest_version_id=version_id,
            )

        md5sum, sha256sum = storage.calculate_checksums(content, ("md5", "sha256"))
        etag = calc_etag(content)

        file_version = self.create(
            id=version_id,
            file=file,
            content=content,
            etag=etag,
            md5sum=md5sum,
            sha256sum=sha256sum,
            size=content.size,
            uploaded_by=uploaded_by,
            uploaded_at=uploaded_at,
            created_at=created_at,
        )

        # TODO most probably we need to select_for_update the `file` object?
        file.latest_version = file_version
        file.latest_version_count = F("latest_version_count") + 1
        file.save(update_fields=["latest_version", "latest_version_count"])

        return file_version


def get_file_version_upload_to(instance: "FileVersion", _filename: str) -> str:
    if instance.file.file_type == File.FileType.PROJECT_FILE:
        return f"projects/{instance.file.project.id}/files/{instance.file.name}/{instance.display}-{str(instance.id)[0:8]}"
    elif instance.file.file_type == File.FileType.PACKAGE_FILE:
        # TODO decide whether we need to add the version id in there?
        # Currently we don't add it, since there is no situation to have multiple versions of the same file in a packaged file.
        # On the other hand, having this differing from regular files will make it harder to manage.
        return f"projects/{instance.file.project.id}/packages/{instance.file.package_job_id}/{instance.file.name}"
    else:
        raise NotImplementedError()


class FileVersion(models.Model):
    def _get_file_storage_name(self) -> str:
        """Returns the file storage name where all the files are stored. Used by `DynamicStorageFileField` and `DynamicStorageFieldFile`."""
        return self.file.project.file_storage

    class Meta:
        ordering = ("file", "-uploaded_at")

    objects = FileVersionQueryset.as_manager()

    # The version primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # File object this FileVersion belongs to.
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        related_name="versions",
        editable=False,
    )

    # The filename as on the storage service. Django will automatically convert it to `ContentFile`. Should be in the following format: projects/<project_id>/<filename>.<extension>/<display>
    content = DynamicStorageFileField(
        upload_to=get_file_version_upload_to,
        # the s3 storage has 1024 bytes (not chars!) limit: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        max_length=1024,
    )

    # MD5-like sum but calculated the same way as S3 calculates it on multistage upload.
    etag = models.TextField(max_length=255, editable=False)

    # MD5 sum of the file.
    md5sum = models.BinaryField(max_length=16)

    # SHA256 sum of the file.
    sha256sum = models.BinaryField(max_length=32)

    # Size of the file in bytes.
    size = models.PositiveIntegerField(editable=False)

    # Timestamp when the file has been uploaded.
    uploaded_at = models.DateTimeField(default=timezone.now, editable=False)

    # User who uploaded the file. If the user is deleted, the field will automatically be assigned to the project owner.
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        editable=False,
        null=True,
    )

    # Timestamp when the `FileVersion` record was inserted in the database.
    # TODO We do not `auto_now_add=True` to be able to set this when migrating files from legacy to the regular storage. Switch to `auto_now_add=True` when the legacy storage is no longer supported.
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    @property
    def display(self) -> str:
        return self.uploaded_at.strftime("v%Y%m%d%H%M%S")

    @property
    def previous_version(self) -> "FileVersion | None":
        file_version_qs = FileVersion.objects.filter(
            file=self.file,
            uploaded_at__lt=self.uploaded_at,
        ).order_by("-uploaded_at")

        return file_version_qs.first()

    @property
    def next_version(self) -> "FileVersion | None":
        file_version_qs = FileVersion.objects.filter(
            file=self.file,
            uploaded_at__lt=self.uploaded_at,
        ).order_by("uploaded_at")

        return file_version_qs.first()

    def delete(self, *args, **kwargs):
        self.content.delete()
        super().delete(*args, **kwargs)

    def __repr__(self) -> str:
        return f'FileVersion({self.id}) in "{self.file.project_id}" "{self.file.name}" "{self.display}"'  # type: ignore

    def __str__(self) -> str:
        return self.__repr__()