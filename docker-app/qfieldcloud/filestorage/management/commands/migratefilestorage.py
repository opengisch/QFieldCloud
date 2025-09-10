import traceback
import uuid
from collections.abc import Collection
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from qfieldcloud.core.models import Project
from qfieldcloud.filestorage.migrate_project_storage import (
    migrate_project_storage,
    setup_fs_migration_logger,
)

logger = setup_fs_migration_logger()


DEFAULT_STORAGE = "default"


class Command(BaseCommand):
    """
    Migrate project from one legacy storage to another storage.
    """

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", default=False)
        parser.add_argument("--accept", action="store_true", default=False)
        parser.add_argument("--no-raise", action="store_true", default=False)

        group = parser.add_mutually_exclusive_group()

        group.add_argument("--project-id", type=uuid.UUID, nargs="?")
        group.add_argument("--all", action="store_true", default=None)
        group.add_argument("--owner-username-startswith", type=str)
        group.add_argument("--owner-username-matches", type=str)

        filter_group = parser.add_argument_group("--all options")

        filter_group.add_argument("--no-filter", action="store_true", default=False)
        filter_group.add_argument(
            "--advanced-filter",
            action="store_true",
            help="Allows to filter all projects using date (--updated-until) and community only (--only-community)",
            default=False,
        )

        adv_filter_group = parser.add_argument_group("--advanced-filter options")
        adv_filter_group.add_argument(
            "--updated-until",
            type=str,
            help="Migrate only projects updated until this date, using format YYYY-MM-DD. Active only if --all and --advanced-filter arguments are passed.",
        )
        adv_filter_group.add_argument(
            "--only-community",
            action="store_true",
            help="Migrate only projects owned by community accounts. Active only if --all and --advanced-filter arguments are passed.",
            default=False,
        )

    def handle(self, *args, **options) -> None:
        projects: Collection = []

        force: bool = options.get("force", False)
        accept: bool = options.get("accept", False)
        no_raise: bool = options.get("no_raise", False)

        # these should be alternative to each other
        project_id = options.get("project_id")
        all = options.get("all")
        owner_username_startswith = options.get("owner_username_startswith")
        owner_username_matches = options.get("owner_username_matches")
        no_filter = options.get("no_filter", False)
        advanced_filter = options.get("advanced_filter", False)
        updated_until = options.get("updated_until")
        only_community = options.get("only_community", False)

        # exclude from migration the projects that already use the default storage.
        project_qs = Project.objects.exclude(
            file_storage=DEFAULT_STORAGE,
        )

        if all is not None:
            assert project_id is None
            assert owner_username_startswith is None
            assert owner_username_matches is None

            if not no_filter and not advanced_filter:
                self.stderr.write(
                    "Can not migrate all projects files without --no-filter or --advanced-filter options."
                )
                exit(1)

            if no_filter and advanced_filter:
                self.stderr.write(
                    "Can not use --no-filter and --advanced-filter options together."
                )
                exit(1)

            if no_filter:
                self.stdout.write(
                    "You are going to migrate all files on this installation, without any project filtering!"
                    "This will take a long time to finish and should be done only if you know what is going on!"
                )

            if advanced_filter:
                if not updated_until and not only_community:
                    self.stderr.write(
                        "You are using advanced filtering, but no specific filters are set. Please use one."
                    )
                    exit(1)

                if updated_until:
                    dt_naive = datetime.fromisoformat(updated_until)
                    dt_zoned = timezone.make_aware(dt_naive)

                    self.stdout.write(
                        f"You are going to migrate projects updated until '{dt_zoned}'."
                    )

                if only_community:
                    self.stdout.write(
                        "You are going to migrate projects owned by community accounts."
                    )

            if not accept:
                yes_no = input("Are you sure you want to continue? [y/n]\n")
                if yes_no != "y":
                    self.stderr.write(
                        "The files migration will not happen, probably a good choice!"
                    )
                    return

            if advanced_filter:
                if updated_until:
                    project_qs = project_qs.filter(data_last_packaged_at__lt=dt_zoned)

                if only_community:
                    project_qs = project_qs.filter(
                        owner__useraccount__current_subscription_vw__plan__code__in=[
                            "community",
                            "trial_organization",
                        ]
                    )

        elif project_id is not None:
            assert all is None
            assert owner_username_startswith is None
            assert owner_username_matches is None

            project_qs = project_qs.filter(id=project_id)
        elif owner_username_startswith is not None:
            assert all is None
            assert project_id is None
            assert owner_username_matches is None

            project_qs = project_qs.filter(
                owner__username__startswith=owner_username_startswith,
            )
        elif owner_username_matches is not None:
            assert all is None
            assert project_id is None
            assert owner_username_startswith is None

            project_qs = project_qs.filter(
                owner__username=owner_username_matches,
            )
        else:
            self.stderr.write(
                "You must pass exactly one of filter arguments: --project-id, --all, --owner-username-startswith, or --owner-username-matches!"
            )

            exit(1)

        projects_count = project_qs.count()
        if projects_count == 0:
            self.stderr.write("No projects match the passed filters!")

            exit(1)

        self.stdout.write(
            f"The storage migration will affect {len(projects)} project(s):"
        )

        self.stdout.write("ID\tNAME")
        for project in project_qs:
            self.stdout.write(f"{project.id}\t{project.owner.username}/{project.name}")

        if not accept:
            yes_no = input("Are you sure you want to continue? [y/n]\n")

            if yes_no != "y":
                self.stderr.write(
                    "The files migration will not happen, probably a good choice!"
                )
                return

        for index, project in enumerate(project_qs, start=1):
            self.stdout.write(
                f'⏳ {index}/{projects_count}: migrating storage for project "{project.name}" ({project.id}) from "{project.file_storage}" to "default".'
            )

            try:
                migrate_project_storage(project, DEFAULT_STORAGE, force)
            except Exception as err:
                self.stderr.write(
                    f"Error when migrating project '{project.name}' ({project.id}): {err}"
                )

                if no_raise:
                    self.stderr.write(traceback.format_exc())
                else:
                    raise
