import logging
import uuid
from collections.abc import Collection

from django.core.management.base import BaseCommand
from qfieldcloud.core.models import Project

from ...migrate_project_storage import migrate_project_storage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Migrate project from one legacy storage to another storage.
    """

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", default=False)

        group = parser.add_mutually_exclusive_group()

        group.add_argument("--project-id", type=uuid.UUID, nargs="?")
        group.add_argument("--all", action="store_true", default=None)
        group.add_argument("--owner-username-startswith", type=str)
        group.add_argument("--owner-username-matches", type=str)

    def handle(self, *args, **options) -> None:
        projects: Collection = []

        force: bool = options.get("force", False)

        # these should be alternative to each other
        project_id = options.get("project_id")
        all = options.get("all")
        owner_username_startswith = options.get("owner_username_startswith")
        owner_username_matches = options.get("owner_username_matches")

        if all is not None:
            assert project_id is None
            assert owner_username_startswith is None
            assert owner_username_matches is None

            self.stderr.write(
                "You are going to migrate all files on this installation."
                "This will take a long time to finish and should be done only if you know what is going on!"
            )

            yes_no = input("Are you sure you want to continue? [y/n]\n")

            if yes_no != "y":
                self.stderr.write(
                    "The files migration will not happen, probably a good choice!"
                )
                return

            projects = Project.objects.all()
        elif project_id is not None:
            assert all is None
            assert owner_username_startswith is None
            assert owner_username_matches is None

            projects = [Project.objects.get(pk=project_id)]
        elif owner_username_startswith is not None:
            assert all is None
            assert project_id is None
            assert owner_username_matches is None

            projects = Project.objects.filter(
                owner__username__startswith=owner_username_startswith,
            )
        elif owner_username_matches is not None:
            assert all is None
            assert project_id is None
            assert owner_username_startswith is None

            projects = Project.objects.filter(
                owner__username=owner_username_matches,
            )
        else:
            self.stderr.write(
                "You must pass exactly one of filter arguments: --project-id, --all, --owner-username-startswith, or --owner-username-matches!"
            )

            exit(1)

        if len(projects) == 0:
            self.stderr.write("No projects match the passed filters!")

            exit(1)

        self.stderr.write(
            f"The storage migration will affect {len(projects)} project(s):"
        )

        self.stderr.write("ID\tNAME")
        for project in projects:
            self.stderr.write(f"{project.id}\t{project.owner.username}/{project.name}")

        yes_no = input("Are you sure you want to continue? [y/n]\n")

        if yes_no != "y":
            self.stderr.write(
                "The files migration will not happen, probably a good choice!"
            )
            return

        for project in projects:
            self.stderr.write(
                f'Migrating storage for project "{project.name}" ({project.id}) from {project.file_storage} to "default".'
            )

            migrate_project_storage(project, "default", force)
