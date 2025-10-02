import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import transaction
from django.utils import timezone

from qfieldcloud.core.models import Job, Project
from qfieldcloud.core.utils import (
    get_project_files_with_versions,
    get_project_package_files,
)
from qfieldcloud.filestorage.models import File, FileVersion

logger = logging.getLogger(__name__)


class ActiveJobsError(Exception): ...


@transaction.atomic
def migrate_project_storage(
    project: Project,
    to_storage: str,
    force: bool = False,
) -> None:
    """Migrates project storage from the old s3 version-enabled storage to platform independent `django-storages`-based file handling.

    Args:
        project: Target project to be migrated
        to_storage: Target storage to migrate to
        force: Overwrite the target storage if the project files already exist by deleting all objects with the project id prefix. Defaults to False.
    """
    logger.info(f'Migrating project "{project.name}" ({str(project.id)})...')

    from_storage = project.file_storage
    from_attachments_storage = project.attachments_file_storage

    # project given as parameter should already have been filtered, to exclude the new/default storage.
    # basically, this should never happen, but we check it just in case.
    if from_storage == to_storage:
        raise Exception(
            f'Cannot migrate to storage "{to_storage}", project {project.id} is already stored there!'
        )

    if from_storage not in settings.STORAGES:
        raise Exception(
            f'Cannot migrate from "{from_storage}", not preset in STORAGES!'
        )

    if from_attachments_storage not in settings.STORAGES:
        raise Exception(
            f'Cannot migrate attachments from "{from_attachments_storage}", not preset in STORAGES!'
        )

    if to_storage not in settings.STORAGES:
        raise Exception(f'Cannot migrate to "{to_storage}", not preset in STORAGES!')

    if project.locked_at is not None:
        raise Exception("Cannot migrate a project that is locked!")

    if not settings.STORAGES[from_storage]["QFC_IS_LEGACY"]:
        raise NotImplementedError(
            "Storage migration is only supported from legacy storage (pre-storages era)!"
        )

    from_storage_bucket = storages[from_storage].bucket  # type: ignore
    to_storage_bucket = storages[to_storage].bucket  # type: ignore
    now = timezone.now()

    try:
        logger.debug(f'Locking project "{project.name}" ({str(project.id)})...')

        project.locked_at = now
        project.save(update_fields=["locked_at"])

        logger.debug(f'Project "{project.name}" ({str(project.id)}) locked!')

        # NOTE do not allow migration on projects that have currently active jobs.
        # The worker wrapper is going to skip all PENDING jobs for locked projects.
        active_jobs_count = Job.objects.filter(
            project=project,
            status__in=[
                Job.Status.QUEUED,
                Job.Status.STARTED,
            ],
        ).count()

        if active_jobs_count:
            raise ActiveJobsError(
                f'Cannot migrate a project with active jobs, {active_jobs_count} jobs are active for project "{project.name}" ({str(project.id)})!'
            )

        logger.debug(
            f'Getting project files for project "{project.name}" ({str(project.id)})...'
        )

        project_files = list(get_project_files_with_versions(str(project.id)))

        logger.info(
            f'Project files for project "{project.name}" ({str(project.id)}) are {len(project_files)}!'
        )

        if not project_files:
            logger.warning(
                f'No files to migrate for project "{project.name}" ({str(project.id)})!'
            )

        # NOTE we must set the Project's `file_storage` and `attachments_file_storage` to the new value before we start adding versions!
        if project.attachments_file_storage == project.file_storage:
            project.attachments_file_storage = to_storage

        project.file_storage = to_storage
        project.save(update_fields=["file_storage", "attachments_file_storage"])

        logger.debug(
            f'Checking for files for project "{project.name}" ({str(project.id)}) already stored in the destination storage...'
        )

        s3_objects = list(
            to_storage_bucket.objects.filter(
                Prefix=f"projects/{project.id}",
            ).limit(1)
        )

        if len(s3_objects) > 0:
            if force:
                logger.warning(
                    f'Removing {len(project_files)} file(s) from the target storage for "{project.name}" ({str(project.id)})...'
                )

                to_storage_bucket.objects.filter(
                    Prefix=f"projects/{project.id}",
                ).delete()
            else:
                raise Exception(
                    f'Cannot migrate project "{project.name}" ({str(project.id)}) to "{to_storage}", the path already exists in the bucket!!'
                )

        for project_file in project_files:
            for file_version in project_file.versions:
                logger.info(
                    f'Migrating file "{file_version.name}" with version "{file_version.id}" for "{project.name}" ({str(project.id)})...'
                )

                django_content_file = ContentFile(b"", file_version.name)

                from_storage_bucket.download_fileobj(
                    file_version.key,
                    django_content_file,
                    {
                        "VersionId": file_version.id,
                    },
                )

                new_file_version = FileVersion.objects.add_version(
                    project=project,
                    filename=file_version.name,
                    content=django_content_file,
                    file_type=File.FileType.PROJECT_FILE,
                    uploaded_at=file_version.last_modified,
                    uploaded_by=project.owner,
                    created_at=now,
                    legacy_version_id=file_version.id,
                )

                # check that etags before and after are the same.
                legacy_storage_etag = file_version.e_tag.strip('"')

                new_file_version.content.open()
                to_storage_etag = new_file_version.content._file.obj.e_tag.strip('"')
                new_file_version.content.close()

                if legacy_storage_etag != to_storage_etag:
                    raise Exception(
                        f"ETag mismatch: '{new_file_version}' on legacy has value {legacy_storage_etag} but new storage has {to_storage_etag} !"
                    )

                if legacy_storage_etag != new_file_version.etag:
                    raise Exception(
                        f"ETag mismatch: version object has ETag {new_file_version.etag} but remote systems have {to_storage_etag} !"
                    )

        package_files = []

        for package_job in project.latest_package_jobs():
            package_job_files = get_project_package_files(
                str(project.id),
                str(package_job.id),
            )

            for package_job_file in package_job_files:
                package_files.append((package_job, package_job_file))

        logger.info(
            f'Migrating {len(package_files)} package file(s) for project "{project.name}" ({str(project.id)})...'
        )

        if len(package_files) > 0:
            for package_job, package_file in package_files:
                django_content_file = ContentFile(b"", package_file.name)

                from_storage_bucket.download_fileobj(
                    package_file.key,
                    django_content_file,
                )

                new_file_version = FileVersion.objects.add_version(
                    project=project,
                    filename=package_file.name,
                    content=django_content_file,
                    file_type=File.FileType.PACKAGE_FILE,
                    uploaded_at=package_file.last_modified,
                    uploaded_by=project.owner,
                    created_at=now,
                    package_job_id=package_job.id,
                )

                # check that etags before and after are the same.
                legacy_storage_etag = package_file.etag.strip('"')

                new_file_version.content.open()
                to_storage_etag = new_file_version.content._file.obj.e_tag.strip('"')
                new_file_version.content.close()

                if legacy_storage_etag != to_storage_etag:
                    raise Exception(
                        f"ETag package mismatch: '{new_file_version}' on legacy has value {legacy_storage_etag} but new storage has {to_storage_etag} !"
                    )

                if legacy_storage_etag != new_file_version.etag:
                    raise Exception(
                        f"ETag package mismatch: version object has ETag {new_file_version.etag} but remote systems have {to_storage_etag} !"
                    )

        if project.legacy_thumbnail_uri:
            logger.info(
                f'Migrate project "{project.name}" ({str(project.id)}) thumbnail "{project.legacy_thumbnail_uri}"...'
            )

            django_thumbnail_file = ContentFile(b"", project.legacy_thumbnail_uri)
            from_storage_bucket.download_fileobj(
                project.legacy_thumbnail_uri,
                django_thumbnail_file,
            )
            project.thumbnail = django_thumbnail_file  # type: ignore

            logger.debug(
                f'Migrated project "{project.name}" ({str(project.id)}) thumbnail!'
            )
        else:
            logger.info(
                f'No thumbnail to migrate for project "{project.name}" ({str(project.id)})'
            )

        project.file_storage_migrated_at = now

    except Exception as err:
        # TODO make sure the created data is deleted from the destination storage if something fails

        logger.error(
            f'File migration failed for "{project.name}" ({project.id}) {from_storage=} {to_storage=} with error: {str(err)}',
            exc_info=err,
        )

        logger.info(
            f'Deleting all files stored in the new storage "{to_storage}" for project "{project.name}" ({str(project.id)})!'
        )

        result_list = to_storage_bucket.objects.filter(
            Prefix=f"projects/{project.id}",
        ).delete()

        assert len(result_list) <= 1

        if result_list:
            result_count = len(result_list[0]["Deleted"])
        else:
            result_count = 0

        logger.info(
            f'Deleted {result_count} file(s) in the new storage "{to_storage}" for project "{project.name}" ({str(project.id)})!'
        )

        # restore the old storage, it will be saved in the `finally` block
        project.file_storage = from_storage
        project.attachments_file_storage = from_attachments_storage

        raise err
    finally:
        project.locked_at = None
        project.save(
            update_fields=[
                "locked_at",
                "file_storage",
                "attachments_file_storage",
                "file_storage_migrated_at",
                "thumbnail",
            ]
        )
