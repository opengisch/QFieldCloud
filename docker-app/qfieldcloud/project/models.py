from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db.models import Case, Exists, F, OuterRef, Q, When
from django.db.models import Value as V
from django.db.models.aggregates import Count, Sum
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django_stubs_ext import StrOrPromise

from qfieldcloud.core import validators
from qfieldcloud.core.fields import DynamicStorageFileField
from qfieldcloud.core.models import (
    Job,
    Organization,
    PackageJob,
    PackageJobQuerySet,
    Person,
    PersonQueryset,
    Secret,
    TeamMember,
    User,
)

if TYPE_CHECKING:
    from qfieldcloud.core.models import (
        JobQuerySet,
        ProjectCollaboratorQueryset,
        SecretQueryset,
    )
    from qfieldcloud.filestorage.models import File, FileQueryset

    pass

SHARED_DATASETS_PROJECT_NAME = "shared_datasets"
logger = logging.getLogger(__name__)


class ProjectQueryset(models.QuerySet):
    """Adds for_user(user) method to the project's querysets, allowing to filter only projects visible to that user.

    Projects are annotated with the user's role (`user_role`) and the origin of this role (`user_role_origin`).

    Args:
        user:               user to check permission for

    Usage:
    ```
    # List Olivier's projects that are visible to Ivan (olivier/ivan are User instances)
    olivier.projects.for_user(ivan)
    ```

    Note:
    This query is very similar to `PersonQueryset.for_project`, don't forget to update it too.
    """

    def for_user(self, user: "User", skip_invalid: bool = False):
        count = Count(
            "collaborators",
            filter=Q(collaborators__collaborator__type=User.Type.PERSON),
        )
        is_public_q = Q(is_public=True)
        is_person_q = Q(owner__type=User.Type.PERSON)
        is_org_q = Q(owner__type=User.Type.ORGANIZATION)
        is_org_member_q = Q(owner__type=User.Type.ORGANIZATION) & Exists(
            Organization.objects.of_user(user)  # type: ignore
            .select_related(None)
            .filter(id=OuterRef("owner"))
        )
        max_premium_collaborators_per_private_project_q = Q(
            owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project=V(
                -1
            )
        ) | Q(
            owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project__gte=count
        )

        # Assemble the condition
        is_valid_user_role_q = is_public_q | (
            max_premium_collaborators_per_private_project_q
            & (is_person_q | (is_org_q & is_org_member_q))
        )

        qs = (
            self.defer("user_roles__user_id", "user_roles__project_id")
            .filter(
                user_roles__user=user,
            )
            .select_related("owner")
            .annotate(
                user_role=F("user_roles__name"),
                user_role_origin=F("user_roles__origin"),
                user_role_is_valid=Case(
                    When(is_valid_user_role_q, then=True), default=False
                ),
                user_role_is_incognito=F("user_roles__is_incognito"),
            )
        )

        if skip_invalid:
            qs = qs.filter(user_role_is_valid=True)

        return qs


def get_project_file_storage_default() -> str:
    """Get the default file storage for the newly created project

    Returns:
        the name of the storage
    """
    return settings.STORAGES_PROJECT_DEFAULT_STORAGE


def get_project_attachments_file_storage_default() -> str:
    """Get the default attachments file storage for the newly created project.

    Returns:
        the name of the storage
    """
    return settings.STORAGES_PROJECT_DEFAULT_ATTACHMENTS_STORAGE


def get_project_are_attachments_versioned_default() -> bool:
    """Get the default value for versioning of project attachments.

    Returns:
        whether the attachments are versioned by default
    """
    return settings.STORAGE_PROJECT_DEFAULT_ATTACHMENTS_VERSIONED


def get_project_thumbnail_upload_to(instance: "Project", _filename: str) -> str:
    """Variable storage key for thumbnails.

    We use a variable storage key to avoid creating object storage level versions for
    thumbnails that we then would need to manage (purge old versions, make sure we don't
    exceed version limit).
    """
    ts = datetime.now().strftime("v%Y%m%d%H%M%S")
    # Random suffix because the second precision of the timestamp alone might
    # not be enough to avoid collisions
    suffix = str(uuid4())[:8]
    return f"projects/{instance.id}/meta/thumbnail_{ts}_{suffix}.png"


class Project(models.Model):
    """Represent a QFieldcloud project.
    It corresponds to a directory on the file system.

    The owner of a project is an Organization.
    """

    # NOTE the status is NOT stored in the db, because it might be refactored
    class Status(models.TextChoices):
        OK = "ok", _("Ok")
        BUSY = "busy", _("Busy")
        FAILED = "failed", _("Failed")

    class StatusCode(models.TextChoices):
        OK = "ok", _("Ok")
        FAILED_PROCESS_PROJECTFILE = (
            "failed_process_projectfile",
            _("Failed process projectfile"),
        )
        TOO_MANY_COLLABORATORS = "too_many_collaborators", _("Too many collaborators")

    class PackagingOffliner(models.TextChoices):
        QGISCORE = "qgiscore", _("QGIS Core Offline Editing (deprecated)")
        PYTHONMINI = "pythonmini", _("Optimized Packager")

    class ProjectType(models.IntegerChoices):
        REGULAR = 1, _("Regular")
        SHARED_DATASETS = 2, _("Shared Datasets")

    @property
    def localized_layers(self) -> list[dict[str, Any]]:
        """
        Retrieve all layers from `Project.project_details` that have their `is_localized` flag set to `True`.

        Returns:
            A list of layer detail dictionaries where each dict has 'is_localized' == True.
            If project_details is missing or empty, returns an empty list.
        """
        if not self.project_details:
            return []

        layers_by_id = self.project_details.get("layers_by_id", {})

        localized_layers = []
        for layer_detail in layers_by_id.values():
            if layer_detail.get("is_localized", False):
                localized_layers.append(layer_detail)

        return localized_layers

    def _get_file_storage_name(self) -> str:
        """Returns the file storage name where all the files are stored. Used by `DynamicStorageFileField` and `DynamicStorageFieldFile`."""
        return self.file_storage

    objects = ProjectQueryset.as_manager()

    _status_code = StatusCode.OK

    class Meta:
        ordering = ["-is_featured", "owner__username", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="project_owner_name_uniq"
            )
        ]

    # All files related to the project, including both the `PROJECT_FILE` and `PACKAGE_FILE` file types.
    all_files: "FileQueryset"

    # The secrets that are attached for a specific project.
    secrets: "SecretQueryset"

    # The jobs that are ran for a specific project.
    jobs: "JobQuerySet"

    # The project create seed.
    seed: "ProjectSeed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                r"^[a-zA-Z0-9-_\.]+$",
                _("Only letters, numbers, underscores, hyphens and dots are allowed."),
            )
        ],
        help_text=_(
            _("Only letters, numbers, underscores, hyphens and dots are allowed.")
        ),
    )

    description = models.TextField(blank=True)

    the_qgis_file_id: int | None
    the_qgis_file = models.ForeignKey(
        "filestorage.File",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    project_details = models.JSONField(blank=True, null=True)
    is_public = models.BooleanField(
        default=False,
        help_text=_(
            "Projects marked as public are visible to (but not editable by) anyone."
        ),
    )

    project_type = models.IntegerField(
        choices=ProjectType.choices, default=ProjectType.REGULAR
    )

    # the Person or Organization id that owns the project
    owner_id: int

    # the Person or Organization that owns the project
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="projects",
        limit_choices_to=models.Q(type__in=[User.Type.PERSON, User.Type.ORGANIZATION]),
        help_text=_(
            "The project owner can be either you or any of the organization you are member of."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # These cache stats of the S3 storage. These can be out of sync, and should be
    # refreshed whenever retrieving/uploading files by passing `project.save(recompute_storage=True)`
    file_storage_bytes = models.PositiveBigIntegerField(default=0)

    # NOTE we can track only the file based layers, WFS, WMS, PostGIS etc are impossible to track
    data_last_updated_at = models.DateTimeField(blank=True, null=True)
    data_last_packaged_at = models.DateTimeField(blank=True, null=True)

    last_package_job_id: uuid.UUID
    last_package_job = models.ForeignKey(
        "core.PackageJob",
        on_delete=models.SET_NULL,
        related_name="last_job_of",
        null=True,
        blank=True,
    )

    repackaging_cache_expire = models.DurationField(
        default=timedelta(minutes=60),
        validators=[MinValueValidator(timedelta(minutes=1))],
    )

    overwrite_conflicts = models.BooleanField(
        default=True,
        help_text=_(
            "If enabled, QFieldCloud will automatically overwrite conflicts in this project. Disabling this will force the project manager to manually resolve all the conflicts."
        ),
    )

    has_restricted_projectfiles = models.BooleanField(
        default=False,
        verbose_name=_("Restrict project files"),
        help_text=_(
            "If enabled, modifications of QGIS project configuration (.qgs, qgz, qgd) and QField project plugins files will be restricted to managers and administrators."
        ),
    )

    thumbnail = DynamicStorageFileField(
        _("Thumbnail Picture"),
        upload_to=get_project_thumbnail_upload_to,
        # the s3 storage has 1024 bytes (not chars!) limit: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        max_length=1024,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=("png", "jpg")),
            validators.MaxImageDimensionValidator(
                settings.QFIELDCLOUD_PROJECT_THUMBNAIL_MAX_DIMENSION
            ),
            validators.MaxFileSizeValidator(
                settings.QFIELDCLOUD_PROJECT_THUMBNAIL_MAX_BYTES
            ),
        ],
    )

    # Duplicating logic from the plan's storage_keep_versions
    # so that users use less file versions (therefore storage)
    # than as per their plan's default on specific projects.
    # WARNING: If storage_keep_versions == 0, it will delete all file versions (hence the file itself) !
    storage_keep_versions = models.PositiveIntegerField(
        _("File versions to keep"),
        help_text=_(
            "Use this value to limit the maximum number of file versions. If empty, your current plan's default will be used. Not configurable for free users."
        ),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )

    # Packaging offliner to be used by the QGIS worker container.
    packaging_offliner = models.CharField(
        _("Packaging Offliner"),
        help_text=_(
            'The Packaging Offliner packages data for offline use with QField. The new "Optimized Packager" should be preferred over the deprecated "QGIS Core Offline Editing" for new projects.'
        ),
        max_length=100,
        default=PackagingOffliner.PYTHONMINI,
        choices=PackagingOffliner.choices,
    )

    file_storage = models.CharField(
        _("File storage"),
        help_text=_(
            "Which file storage provider should be used for the storing the project related files."
        ),
        max_length=100,
        validators=[validators.file_storage_name_validator],
        default=get_project_file_storage_default,
    )

    qgis_version = models.CharField(
        _("QGIS project version"),
        help_text=_(
            "The QGIS project version as detected from the uploaded project file."
        ),
        max_length=100,
        null=True,
        blank=True,
        editable=False,
    )

    file_storage_migrated_at = models.DateTimeField(
        _("File Storage Migrated At"),
        blank=True,
        null=True,
        editable=False,
    )

    locked_at = models.DateTimeField(
        _("Locked at"),
        help_text=_(
            "If not null, it means that the project is being migrated, and the datetime represents when the project was temporarily locked. Locking is internal QFieldCloud mechanism related to file storage migration or other file operations."
        ),
        blank=True,
        null=True,
        editable=False,
    )

    is_featured = models.BooleanField(
        _("Is featured"),
        help_text=_(
            "If set to true, the project will always appear on top of the project list, no matter the sorting. If multiple projects are featured, they will be sorted by the user defined sorting."
        ),
        default=False,
    )

    attachments_file_storage = models.CharField(
        _("Attachments file storage"),
        help_text=_(
            "Which file storage provider should be used for storing the project attachments files."
        ),
        max_length=100,
        validators=[validators.file_storage_name_validator],
        default=get_project_attachments_file_storage_default,
    )

    # When enabled, the client (e.g. QField) is informed that attachments
    # can be fetched on demand at a later stage instead of downloading in bulk with the other package files.
    # This can reduce the size of packaged data, especially for
    # projects with large or numerous attachments.
    is_attachment_download_on_demand = models.BooleanField(
        default=False,
        verbose_name=_("On demand attachment files download"),
        help_text=_(
            "If enabled, attachment files should be downloaded on demand with QField."
        ),
    )

    are_attachments_versioned = models.BooleanField(
        default=get_project_are_attachments_versioned_default,
        verbose_name=_("Versioned attachment files"),
        help_text=_(
            "If enabled, attachment files will make use of the file versioning system. If disabled, only the latest version of each attachment file will be kept, and stored with the extension in the filename."
        ),
    )

    restricted_data_last_updated_at = models.DateTimeField(
        _("Restricted data last updated at"),
        blank=True,
        null=True,
        editable=False,
    )

    @cached_property
    def shared_datasets_project(self) -> Project | None:
        """
        Returns the localized datasets project for the same owner, or `None` if no such project exists.
        """
        try:
            project = Project.objects.get(
                project_type=self.ProjectType.SHARED_DATASETS,
                owner=self.owner,
            )
            return project
        except Project.DoesNotExist:
            return None

    def package_jobs_for_user(self, user: User) -> PackageJobQuerySet:
        """Returns all package jobs for the user.

        Args:
            user: The user to check for.

        Returns:
            QuerySet of all package jobs for the user.
        """
        secret_filters = Q(project=self, organization=None, assigned_to=user)

        if self.owner.is_organization:
            secret_filters |= Q(project=None, organization=self.owner, assigned_to=user)

        secret_qs = Secret.objects.filter(secret_filters)

        jobs_qs = self.jobs.filter(
            type=Job.Type.PACKAGE,
        )

        jobs_qs = jobs_qs.annotate(has_user_secret=Exists(secret_qs)).filter(
            Q(has_user_secret=False) | Q(triggered_by=user)
        )

        return jobs_qs

    def latest_finished_package_job_for_user(self, user: User) -> PackageJob | None:
        """Returns the last finished package job for the user.

        Args:
            user: The user to check for.

        Returns:
            The last finished package job for the user.
        """
        return (
            self.package_jobs_for_user(user)
            .exclude(
                status__in=[
                    Job.Status.PENDING,
                    Job.Status.QUEUED,
                    Job.Status.STARTED,
                ]
            )
            .order_by("-created_at")
            .first()
        )

    def latest_package_job_for_user(self, user: User) -> PackageJob | None:
        """Returns the last package job for the user.

        Args:
            user: The user to check for.

        Returns:
            The last package job for the user.
        """
        return self.package_jobs_for_user(user).order_by("-created_at").first()

    def latest_package_jobs(self) -> PackageJobQuerySet:
        """Returns all the last package jobs for the users of the project.

        Returns:
            QuerySet of all the last package jobs.
        """
        jobs_qs = (
            PackageJob.objects.filter(
                project_id=self.id,
            )
            .order_by("triggered_by", "-created_at")
            .distinct("triggered_by")
        )

        if self.is_public:
            return jobs_qs

        if self.owner.is_organization:
            # all the users including the organization owner
            triggered_by_qs = Person.objects.for_organization(self.owner)
        else:
            triggered_by_qs = Person.objects.filter(id=self.owner.pk)

        triggered_by_qs |= Person.objects.filter(
            id__in=self.direct_collaborators.values_list("collaborator_id", flat=True)
        )
        triggered_by_ids_qs = triggered_by_qs.distinct().values_list("id", flat=True)

        jobs_qs = jobs_qs.filter(triggered_by__in=triggered_by_ids_qs)

        return jobs_qs

    @cached_property
    def is_shared_datasets_project(self) -> bool:
        """
        Returns `True` if the project is the shared datasets project, otherwise `False`.
        """
        return self.project_type == self.ProjectType.SHARED_DATASETS

    def get_missing_localized_layers(self) -> list[dict[str, Any]]:
        """
        Of all localized layers, return those whose filenames aren’t in `available_filenames`,
        which means they are not present in the associated localized datasets project storage.

        Returns:
            A list of layer-detail dicts (same shape as in `localized_layers`)
            that need to be added/uploaded.
        """
        from qfieldcloud.filestorage.models import File

        if not self.project_details:
            return []

        if not self.shared_datasets_project:
            # Return all layers if the project is missing
            return self.localized_layers

        available_filenames = (
            File.objects.with_type_project()
            .filter(project=self.shared_datasets_project)
            .values_list("name", flat=True)
        )

        missing_localized_layers = []
        for layer in self.localized_layers:
            if "filename" not in layer:
                continue
            # TODO: refactor and extract filename splitting logic into a reusable utility.
            filename = layer["filename"].split("localized:")[-1]

            if filename not in available_filenames:
                missing_localized_layers.append(layer)

        return missing_localized_layers

    @property
    def has_the_qgis_file(self) -> bool:
        return self.the_qgis_file_id is not None

    @property
    def the_qgis_file_name(self) -> str | None:
        if not self.the_qgis_file_id:
            return None

        return self.the_qgis_file.name

    @property
    def owner_aware_storage_keep_versions(self) -> int:
        """Determine the storage versions to keep based on the owner's subscription plan and project settings.

        Returns:
            the number of file versions, should be always greater than 1
        """
        subscription = self.owner.useraccount.current_subscription

        if subscription.plan.is_premium:
            keep_count = (
                self.storage_keep_versions or subscription.plan.storage_keep_versions
            )
        else:
            keep_count = subscription.plan.storage_keep_versions

        assert keep_count >= 1, "Ensure that we don't destroy all file versions!"

        return keep_count

    @property
    def thumbnail_url(self) -> StrOrPromise:
        """Returns the url to the project's thumbnail or empty string if no URL provided."""
        if not self.thumbnail:
            return ""

        return reverse_lazy(
            "filestorage_project_thumbnails",
            kwargs={
                "project_id": self.id,
            },
        )

    def __str__(self):
        return self.name + " (" + str(self.id) + ")" + " owner: " + self.owner.username

    @property
    def name_with_owner(self) -> str:
        return f"{self.owner.username}/{self.name}"

    @property
    def attachment_dirs(self) -> list[str]:
        """Returns a list of configured attachment dirs for the project.

        Attachment dir is a special directory in the QField infrastructure that holds attachment files
        such as images, pdf etc. By default "DCIM" is considered a attachment directory.

        Returns:
            A list configured attachment dirs for the project.
        """
        attachment_dirs = []

        if self.project_details and self.project_details.get("attachment_dirs"):
            attachment_dirs = self.project_details.get("attachment_dirs", [])

        if not attachment_dirs:
            attachment_dirs = ["DCIM"]

        return attachment_dirs

    @property
    def data_dirs(self) -> list[str]:
        """Returns a list of configured data dirs for the project.

        Data dir is a special directory in the QField infrastructure that holds assets
        used by the project symbology, layouts, or project plugins.

        Unlike `attachmentDirs`, the `dataDirs` should always be served as a undivisible
        part of project files.

        Returns:
            A list configured data dirs for the project.
        """
        data_dirs = []

        if self.project_details and self.project_details.get("data_dirs"):
            data_dirs = self.project_details.get("data_dirs", [])

        return data_dirs

    @property
    def has_attachments_files(self) -> bool:
        """
        Checks if the project has at least one attachment file.
        """
        return any(f.is_attachment() for f in self.project_files)

    @property
    def private(self) -> bool:
        # still used in the project serializer
        return not self.is_public

    @property
    def project_files(self) -> "FileQueryset":
        """Returns the files of type PROJECT related to the project."""
        return self.all_files.with_type_project()

    @property
    def project_files_count(self) -> int:
        return self.project_files.count()

    @property
    def users(self):
        return User.objects.for_project(self)

    @property
    def has_online_vector_data(self) -> bool | None:
        """Returns None if project details or layers details are not available"""

        if not self.project_details or not self.project_details.get("layers_by_id"):
            return None

        from qfieldcloud.project.utils.project_utils import has_online_vector_data

        return has_online_vector_data(self)

    @property
    def can_repackage(self) -> bool:
        return True

    def needs_repackaging(self, user: User) -> bool:
        latest_package_job_for_user = self.latest_package_job_for_user(user)

        if (
            # if has_online_vector_data is None (happens when the project details are missing)
            # we assume there might be
            self.has_online_vector_data is False
            and self.data_last_updated_at
            and self.data_last_packaged_at
            and latest_package_job_for_user
        ):
            # if all vector layers are file based and have been packaged for the user after the last update,
            # it is safe to say there are no modifications.
            if latest_package_job_for_user.finished_at:
                return (
                    latest_package_job_for_user.finished_at < self.data_last_updated_at
                )
            else:
                return True
        else:
            # if the project has online vector layers (PostGIS/WFS/etc) we cannot be sure if there are modification or not, so better say there are
            return True

    def has_active_create_job(self) -> bool:
        """Check if there's an active create_project job."""
        if not hasattr(self, "seed") or self.seed is None:
            return False

        return self.jobs.filter(
            type=Job.Type.CREATE_PROJECT,
            status__in=[Job.Status.PENDING, Job.Status.QUEUED, Job.Status.STARTED],
        ).exists()

    @property
    def problems(self) -> list[dict[str, Any]]:
        problems = []

        # If there is an active create job, return empty list
        if self.has_active_create_job():
            problems.append(
                {
                    "layer": None,
                    "level": "info",
                    "code": "project_being_created",
                    "description": _("Project being created."),
                    "solution": _(
                        "Your project is currently being set up. This may take a few moments."
                    ),
                }
            )

            return problems

        # Check if localized datasets project, then skip the rest of the checks as they are not applicable
        if self.is_shared_datasets_project:
            if self.has_the_qgis_file:
                problems.append(
                    {
                        "layer": None,
                        "level": "error",
                        "code": "qgis_project_file_not_allowed",
                        "description": _(
                            "Shared datasets projects cannot contain QGIS project files (.qgs/.qgz)."
                        ),
                        "solution": _(
                            "Remove the QGIS project file (.qgs/.qgz) or rename the project to use it normally."
                        ),
                    }
                )

            return problems

        if not self.has_the_qgis_file:
            problems.append(
                {
                    "layer": None,
                    "level": "error",
                    "code": "missing_projectfile",
                    "description": _("Missing QGIS project file (.qgs/.qgz)."),
                    "solution": _(
                        "Make sure a QGIS project file (.qgs/.qgz) is uploaded to QFieldCloud. Reupload the file if problem persists."
                    ),
                }
            )

        elif self.project_details:
            if self.localized_layers:
                if self.shared_datasets_project:
                    localized_project_url = reverse_lazy(
                        "project_overview",
                        kwargs={
                            "username": self.shared_datasets_project.owner.username,
                            "project": self.shared_datasets_project.name,
                        },
                    )
                    missing_localized_file_solution = _(
                        'Upload the missing file to the "<a href="{}">{}</a>" project or update the layer to point to an available file.'
                    ).format(localized_project_url, SHARED_DATASETS_PROJECT_NAME)
                else:
                    problems.append(
                        {
                            "layer": None,
                            "level": "warning",
                            "code": "missing_localized_project",
                            "description": _('Cannot find the "{}" project.').format(
                                SHARED_DATASETS_PROJECT_NAME
                            ),
                            "solution": _("Ensure the shared dataset project exists."),
                        }
                    )
                    missing_localized_file_solution = _(
                        'Upload the missing file to the "{}" project or update the layer to point to an available file.'
                    ).format(SHARED_DATASETS_PROJECT_NAME)

                for missing_layer in self.get_missing_localized_layers():
                    problems.append(
                        {
                            "layer": missing_layer.get("filename"),
                            "level": "warning",
                            "code": "missing_localized_file",
                            "description": _(
                                'Localized dataset stored at "{}" is missing.'
                            ).format(missing_layer.get("filename")),
                            "solution": missing_localized_file_solution,
                        }
                    )

            for layer_data in self.project_details.get("layers_by_id", {}).values():
                layer_name = layer_data.get("name")

                # All the layers stored in the localized datasets project will be with errors, so we just skip them. We handled them separately before this for loop.
                if layer_data.get("error_code") == "localized_dataprovider":
                    continue

                if layer_data.get("error_code") != "no_error":
                    problems.append(
                        {
                            "layer": layer_name,
                            "level": "warning",
                            "code": "layer_problem",
                            "description": _(
                                'Layer "{}" has an error with code "{}": {}'
                            ).format(
                                layer_name,
                                layer_data.get("error_code"),
                                layer_data.get("error_summary"),
                            ),
                            "solution": _(
                                'Check the latest "process_projectfile" job logs for more info and reupload the project files with the required changes.'
                            ),
                        }
                    )
                # the layer is missing a primary key, warn it is going to be read-only
                elif layer_data.get("layer_type_name") in ("VectorLayer", "Vector"):
                    if layer_data.get("qfc_source_data_pk_name") == "":
                        problems.append(
                            {
                                "layer": layer_name,
                                "level": "warning",
                                "code": "layer_problem",
                                "description": _(
                                    'Layer "{}" does not support the `primary key` attribute. The layer will be read-only on QField.'
                                ).format(layer_name),
                                "solution": _(
                                    "To make the layer editable on QField, store the layer data in a GeoPackage or PostGIS layer, using a single column for the primary key."
                                ),
                            }
                        )
        else:
            problems.append(
                {
                    "layer": None,
                    "level": "error",
                    "code": "missing_project_details",
                    "description": _("Failed to parse metadata from project."),
                    "solution": _("Re-upload the QGIS project file (.qgs/.qgz)."),
                }
            )

        return problems

    @cached_property
    def status(self) -> "Project.Status":
        # NOTE the status is NOT stored in the db, because it might be outdated
        if (
            self.jobs.filter(
                status__in=[Job.Status.QUEUED, Job.Status.STARTED, Job.Status.PENDING]
            )  # type: ignore
        ).exists():
            return Project.Status.BUSY
        else:
            status = Project.Status.OK
            status_code = Project.StatusCode.OK
            max_premium_collaborators_per_private_project = self.owner.useraccount.current_subscription.plan.max_premium_collaborators_per_private_project

            # TODO use self.problems to get if there are project problems
            if (
                not self.has_the_qgis_file or not self.project_details
            ) and not self.is_shared_datasets_project:
                status = Project.Status.FAILED
                status_code = Project.StatusCode.FAILED_PROCESS_PROJECTFILE
            elif (
                not self.is_public
                and max_premium_collaborators_per_private_project != -1
                and max_premium_collaborators_per_private_project
                < self.direct_collaborators.count()
            ):
                status = Project.Status.FAILED
                status_code = Project.StatusCode.TOO_MANY_COLLABORATORS

            self._status_code = status_code
            return status

    @property
    def status_code(self) -> StatusCode:
        return self._status_code

    @property
    def storage_size_perc(self) -> float:
        if self.owner.useraccount.current_subscription.active_storage_total_bytes > 0:
            return (
                self.file_storage_bytes
                / self.owner.useraccount.current_subscription.active_storage_total_bytes
                * 100
            )
        else:
            return 100

    @property
    def direct_collaborators(self) -> ProjectCollaboratorQueryset:
        if self.owner.is_organization:
            exclude_pks = [self.owner.organization.organization_owner_id]
        else:
            exclude_pks = [self.owner_id]

        return (
            self.collaborators.skip_incognito()  # type: ignore[attr-defined]
            .filter(
                collaborator__type=User.Type.PERSON,
            )
            .exclude(
                collaborator_id__in=exclude_pks,
            )
        )

    @property
    def total_collaborators(self) -> PersonQueryset:
        if self.owner.is_organization:
            exclude_pks = [self.owner.organization.organization_owner_id]
        else:
            exclude_pks = [self.owner_id]

        team_collaborators_ids = (
            self.collaborators.skip_incognito()  # type: ignore[attr-defined]
            .filter(collaborator__type=User.Type.TEAM)
            .values_list("collaborator_id", flat=True)
        )
        direct_ids = self.direct_collaborators.values_list("collaborator_id", flat=True)
        team_member_ids = (
            TeamMember.objects.filter(team_id__in=team_collaborators_ids)
            .exclude(member_id__in=exclude_pks)
            .values_list("member_id", flat=True)
        )
        return cast(
            PersonQueryset,
            Person.objects.filter(
                Q(pk__in=direct_ids) | Q(pk__in=team_member_ids)
            ).distinct(),
        )

    @property
    def total_collaborators_count(self) -> int:
        return self.total_collaborators.count()

    @property
    def owner_can_create_job(self):
        # NOTE consider including in status refactoring

        from qfieldcloud.core.permissions_utils import (
            is_supported_regarding_owner_account,
        )

        return is_supported_regarding_owner_account(self)

    def save(self, recompute_storage=False, *args, **kwargs):
        self.clean()
        logger.debug(f"Saving project {self}...")
        additional_update_fields = set()

        if recompute_storage:
            self.file_storage_bytes = self.project_files.aggregate(
                file_storage_bytes=Sum("versions__size", default=0)
            )["file_storage_bytes"]

            additional_update_fields.add("file_storage_bytes")

        # Ensure that the Project's storage_keep_versions is at least 1, and reflects the plan's default storage_keep_versions value.
        if not self.storage_keep_versions:
            self.storage_keep_versions = (
                self.owner.useraccount.current_subscription.plan.storage_keep_versions
            )

            additional_update_fields.add("storage_keep_versions")

        assert self.storage_keep_versions >= 1, (
            "If 0, storage_keep_versions mean that all file versions are deleted!"
        )

        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = list(
                set(kwargs["update_fields"]) | additional_update_fields
            )

        self.project_type = self.ProjectType.REGULAR

        if self.name == SHARED_DATASETS_PROJECT_NAME:
            self.project_type = self.ProjectType.SHARED_DATASETS

        super().save(*args, **kwargs)

    def get_file(self, filename: str) -> File:
        return self.project_files.get_by_name(filename)  # type: ignore


def get_seed_xlsform_upload_to(instance: "ProjectSeed", filename: str) -> str:
    file_extension = Path(filename).suffix.lower()
    return f"projects/{instance.project.id}/seeds/xlsforms/xlsform{file_extension}"


class ProjectSeed(models.Model):
    SETTINGS_SCHEMA_ID = "https://app.qfield.cloud/schemas/project-seed-20251201.json"
    """Represents the seed data version used to create a project."""

    project = models.OneToOneField(
        "project.Project",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="seed",
    )
    """The project the seed refers to."""

    clone_from_project = models.ForeignKey(
        "project.Project",
        on_delete=models.CASCADE,
        null=True,
        related_name="derived_seeds",
        blank=True,
    )
    """The project to copy from, if any. It is mutually exclusive with `xlsform_file`."""

    # TODO @Rakanhf: make the `extent` field not nullable once we add `Project.extent` field.
    extent = models.PolygonField(
        null=True,
        blank=True,
        srid=4326,
    )
    """The initial extent of the project as EPSG:4326 polygon."""

    xlsform_file = models.FileField(
        upload_to=get_seed_xlsform_upload_to,
        # the s3 storage has 1024 bytes (not chars!) limit: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        max_length=1024,
        null=True,
        blank=True,
    )
    """XLSForm file used to create the project, if any. It is mutually exclusive with `clone_from_project`."""

    settings = models.JSONField()
    """The settings used during the project creation. There must be a `schemaId` field."""

    def clean(self, *args, **kwargs) -> None:
        if self.xlsform_file and self.clone_from_project:
            raise ValidationError(
                _(
                    "Both `xlsform_file` or `clone_from_project` cannot be set at the same time."
                )
            )

        # TODO @Rakanhf: make the `extent` field not nullable once we add `Project.extent` field.
        if not self.extent and not self.clone_from_project:
            raise ValidationError(
                _("Either `extent` or `clone_from_project` must be set.")
            )

        if not self.settings.get("schemaId"):
            raise ValidationError(_("The seed settings schemaId must be present."))

        super().clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()

        return super().save(*args, **kwargs)
