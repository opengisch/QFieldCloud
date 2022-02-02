from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from qfieldcloud.core import utils
from qfieldcloud.core.models import Project


class Command(BaseCommand):
    """
    Deletes old versions of files
    """

    PROMPT_TXT = "This will purge old files for all projects. Type 'yes' to continue, or 'no' to cancel: "

    def add_arguments(self, parser):
        parser.add_argument(
            "--projects",
            type=str,
            help="Comma separated list of ids of projects to prune. If unset, will purge all projects",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Prevent confirmation prompt when purging all projects",
        )
        parser.add_argument(
            "--keep_count", type=int, default=10, help="How many versions to keep"
        )

    def handle(self, *args, **options):

        # Determine project ids to work on
        projects_ids = options.get("projects")
        if not projects_ids:
            if options.get("force") is not True and input(Command.PROMPT_TXT) != "yes":
                raise CommandError("Collecting static files cancelled.")
            projects_ids = Project.objects.values_list("id", flat=True)
        else:
            projects_ids = projects_ids.split(",")

        # Get the affected projects
        projects_qs = Project.objects.all()
        if projects_ids:
            projects_qs = projects_qs.filter(pk__in=projects_ids)

        bucket = utils.get_s3_bucket()

        for project_id in projects_ids:
            print(f"Processing project {project_id}")

            prefix = f"projects/{project_id}/files/"
            keep_count = options.get("keep_count")

            # All version under prefix
            all_versions = bucket.object_versions.filter(Prefix=prefix)

            # Organize the versions by file in a dict
            old_versions_by_file = defaultdict(list)
            for version in all_versions:
                # The latest is not an old version
                if version.is_latest:
                    continue
                old_versions_by_file[version.key].append(version)

            # Process file by file
            for filename, old_versions in old_versions_by_file.items():

                # Sort by date (newest first)
                old_versions.sort(key=lambda i: i.last_modified, reverse=True)

                # Skip the newest N
                old_versions_to_purge = old_versions[keep_count:]

                # Debug print
                all_count = len(old_versions)
                topurge_count = len(old_versions_to_purge)
                print(
                    f"{filename}: will purge {topurge_count} out of {all_count} old versions"
                )

                # Remove the N oldest
                for old_version in old_versions_to_purge:
                    old_version.delete()
                    # TODO: audit ? take implementation from files_views.py:211

        print("done !")
