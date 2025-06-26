import logging

from django.db import transaction

from qfieldcloud.core.models import Project

from .models import FileVersion

logger = logging.getLogger(__name__)


def purge_old_file_versions(project: Project) -> None:
    """
    Deletes old versions of all files in the given project. Will keep __3__
    versions for COMMUNITY user accounts, and __10__ versions for PRO user
    accounts
    """

    keep_count = project.owner_aware_storage_keep_versions

    logger.info(f"Cleaning up old files for {project} to {keep_count} versions")

    versions_to_delete_ids = []
    versions_to_delete_size = 0

    for file in project.project_files:
        versions_to_delete = file.versions.order_by("-created_at")[keep_count:]

        if not versions_to_delete:
            continue

        for file_version in versions_to_delete:
            versions_to_delete_ids.append(file_version.id)
            versions_to_delete_size += file_version.size

    if not versions_to_delete_ids:
        return

    with transaction.atomic():
        FileVersion.objects.filter(id__in=versions_to_delete_ids).delete()

        project = Project.objects.select_for_update().get(id=project.id)
        project.file_storage_bytes -= versions_to_delete_size
        project.save(update_fields=["file_storage_bytes"])
