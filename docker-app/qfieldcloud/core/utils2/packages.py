import logging
import uuid
from typing import Iterable

from qfieldcloud.core import models
from qfieldcloud.core.utils2 import storage
from qfieldcloud.filestorage.models import File

logger = logging.getLogger(__name__)


def delete_obsolete_packages(projects: Iterable[models.Project]) -> None:
    """Delete obsolete packages for the given projects.

    We need to keep only the packages that are still in use by users and they are at their latest version.
    Any other packages should be considered obsolete and deleted.

    Arguments:
        projects: Projects to delete obsolete packages for.
    """
    active_package_job_ids = (
        models.Job.objects.filter(
            type=models.Job.Type.PACKAGE,
        )
        .exclude(
            status__in=(models.Job.Status.FAILED, models.Job.Status.FINISHED),
        )
        .values_list("id", flat=True)
    )

    for project in projects:
        # TODO Delete with QF-4963 Drop support for legacy storage
        if project.uses_legacy_storage:
            stored_package_ids = list(
                map(uuid.UUID, storage.get_stored_package_ids(project))
            )

            latest_package_job_ids = project.latest_package_jobs().values_list(
                "id", flat=True
            )

            for stored_package_id in stored_package_ids:
                # the job is still active, so it might be one of the new packages
                if stored_package_id in active_package_job_ids:
                    continue

                # keep packages that are used by other users due to user-assigned secrets.
                shall_skip_package = False
                for latest_package_job_id in latest_package_job_ids:
                    if stored_package_id == latest_package_job_id:
                        shall_skip_package = True
                        break

                if shall_skip_package:
                    continue

                storage.delete_stored_package(project, str(stored_package_id))

        else:
            latest_project_package_jobs_ids = project.latest_package_jobs().values_list(
                "id", flat=True
            )

            files_to_delete_qs = (
                File.objects.filter(
                    project=project,
                    file_type=File.FileType.PACKAGE_FILE,
                )
                .exclude(
                    package_job_id__in=active_package_job_ids,
                )
                .exclude(
                    package_job_id__in=latest_project_package_jobs_ids,
                )
            )

            logger.info(
                "Deleting {} package files from previous and obsolete packages for project id {}:\n{}".format(
                    files_to_delete_qs.count(),
                    project.id,
                    "\n".join(files_to_delete_qs.values_list("name", flat=True)),
                )
            )

            delete_count = files_to_delete_qs.delete()

            logger.info(f"Deleted {delete_count} package files.")
