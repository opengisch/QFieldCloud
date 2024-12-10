from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import File, FileVersion


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
