import uuid

from django.core.management.base import BaseCommand
from qfieldcloud.core.models import Project


class Command(BaseCommand):
    """
    Recalculate projects storage size
    """

    def add_arguments(self, parser):
        parser.add_argument("project_id", type=uuid.UUID, nargs="?")
        parser.add_argument("--force-recalculate", action="store_true")

    def handle(self, *args, **options):
        project_id = options.get("project_id")
        force_recalculate = options.get("force_recalculate")

        extra_filters = {}
        if project_id:
            extra_filters["id"] = project_id

        if not project_id and not force_recalculate:
            extra_filters["file_storage_bytes"] = 0

        projects_qs = Project.objects.filter(
            the_qgis_filename__isnull=False,
            **extra_filters,
        ).order_by("-updated_at")
        total_count = projects_qs.count()

        for idx, project in enumerate(projects_qs):
            print(
                f'Calculating project files storage size for "{project.id}" {idx}/{total_count}...'
            )
            project.save(recompute_storage=True)
            print(
                f'Project files storage size for "{project.id}" is {project.file_storage_bytes} bytes.'
            )
