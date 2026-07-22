import uuid
from enum import StrEnum

from django.core.management.base import BaseCommand
from django.db import transaction

from qfieldcloud.project.models import Project, QgisProject


class BackfillResult(StrEnum):
    # `project` has no QGIS file, so nothing was done.
    SKIPPED = "SKIPPED"
    # A new `QgisProject` was created.
    CREATED = "CREATED"
    # An existing `QgisProject` was re-synced.
    SYNCED = "SYNCED"


def backfill_qgis_project(project: Project) -> BackfillResult:
    """Create/update the `QgisProject` and its `Layer` rows for `project` from `Project.project_details`.

    Runs even if the `QgisProject` already exists.
    """
    if project.the_qgis_file_id is None:
        return BackfillResult.SKIPPED

    is_new = not hasattr(project, "qgis_project")

    QgisProject.objects.update_from_details(
        project, project.the_qgis_file.latest_version, project.project_details
    )
    if is_new:
        return BackfillResult.CREATED
    else:
        return BackfillResult.SYNCED


class Command(BaseCommand):
    """
    Backfill `QgisProject` and `Layer` rows from the `Project.project_details` JSON blob.
    """

    def add_arguments(self, parser):
        parser.add_argument("project_id", type=uuid.UUID, nargs="?")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        project_id = options.get("project_id")
        dry_run = options.get("dry_run")

        extra_filters = {}
        if project_id:
            extra_filters["id"] = project_id

        projects_qs = Project.objects.filter(
            project_details__isnull=False,
            **extra_filters,
        ).order_by("created_at")
        total_count = projects_qs.count()

        counts = dict.fromkeys(BackfillResult, 0)

        for idx, project in enumerate(projects_qs, start=1):
            print(f'Backfilling project "{project.id}" {idx}/{total_count}...')

            if dry_run:
                continue

            with transaction.atomic():
                result = backfill_qgis_project(project)

            counts[result] += 1

        if dry_run:
            print(
                f"Dry run complete. {total_count} projects would have been processed."
            )
        else:
            print(
                f"Done. Created {counts[BackfillResult.CREATED]}, "
                f"re-synced {counts[BackfillResult.SYNCED]}, "
                f"skipped {counts[BackfillResult.SKIPPED]} out of {total_count} projects."
            )
