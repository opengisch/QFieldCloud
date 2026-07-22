import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from qfieldcloud.project.models import Project, QgisProject


def backfill_qgis_project(project: Project) -> bool:
    """Create the `QgisProject` for `project` if it doesn't already exist."""
    if hasattr(project, "qgis_project"):
        return False

    if project.the_qgis_file_id is None:
        return False

    QgisProject.objects.update_from_details(
        project, project.the_qgis_file.latest_version, project.project_details
    )
    return True


class Command(BaseCommand):
    """
    Backfill `QgisProject` (and related) rows from the `Project.project_details` JSON blob.
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

        created_count = 0
        skipped_count = 0

        for idx, project in enumerate(projects_qs, start=1):
            print(f'Backfilling project "{project.id}" {idx}/{total_count}...')

            if dry_run:
                continue

            with transaction.atomic():
                created = backfill_qgis_project(project)

            if created:
                created_count += 1
            else:
                skipped_count += 1

        if dry_run:
            print(
                f"Dry run complete. {total_count} projects would have been processed."
            )
        else:
            print(
                f"Done. Created {created_count}, skipped {skipped_count} out of {total_count} projects."
            )
