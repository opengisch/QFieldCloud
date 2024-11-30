from django.db.models.signals import pre_delete
from django.dispatch import receiver
from qfieldcloud.core.models import User

from .models import File, FileVersion


@receiver(pre_delete, sender=User)
def pre_delete_user(sender, instance, **kwargs):
    user = instance

    files_qs = (
        File.objects.filter(uploaded_by=user)
        .values("project_id", "project__owner_id")
        .distinct()
    )
    versions_qs = (
        FileVersion.objects.filter(uploaded_by=user)
        .values("file__project_id", "file__project__owner_id")
        .distinct()
    )

    for project_dict in files_qs:
        File.objects.filter(
            uploaded_by=user,
            project_id=project_dict["project_id"],
        ).update(
            uploaded_by_id=project_dict["project__owner_id"],
        )

    for project_dict in versions_qs:
        FileVersion.objects.filter(
            uploaded_by=user,
            file__project_id=project_dict["file__project_id"],
        ).update(
            uploaded_by_id=project_dict["file__project__owner_id"],
        )


@receiver(pre_delete, sender=FileVersion)
def pre_delete_file_version(sender, instance, origin, **kwargs):
    """Responsible for setting the `latest_version` of the parent to the correct version."""
    # Do nothing if we are deleting the whole `File` object, not only a single `FileVersion`
    if isinstance(origin, File):
        return

    file_version = instance

    # Do nothing if the file_version is not the latest version
    if file_version.file.latest_version != file_version:
        return

    file_version.file.latest_version = file_version.previous_version
    file_version.file.save(update_fields=["latest_version"])
