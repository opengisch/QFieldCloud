from django.core.management.base import BaseCommand, CommandError
from qfieldcloud.core import utils
from qfieldcloud.core.models import Project, UserAccount


class Command(BaseCommand):

    help = """
    Deletes old versions of files. Will keep only the 3 most recent versions
    for COMMUNITY accounts and the 10 most recent for PRO accounts.
    """

    PROMPT_TXT = "This will purge old files for all projects. Rerun with --force, or type 'yes' to continue, or 'no' to cancel: "

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

    def handle(self, *args, **options):

        # Determine project ids to work on
        proj_ids = options.get("projects")

        # Get the affected projects
        if not proj_ids:
            if options.get("force") is not True and input(Command.PROMPT_TXT) != "yes":
                raise CommandError("Collecting static files cancelled.")
            proj_instances = Project.objects.all()
        else:
            proj_instances = Project.objects.filter(pk__in=proj_ids.split(","))

        # Iterate through projects
        proj_instances = proj_instances.prefetch_related("owner__useraccount")
        for proj_instance in proj_instances:

            print(f"Processing {proj_instance}")

            # Determine account type
            account_type = proj_instance.owner.useraccount.account_type
            if account_type == UserAccount.TYPE_COMMUNITY:
                keep_count = 3
            elif account_type == UserAccount.TYPE_PRO:
                keep_count = 10
            else:
                print("⚠️ Unknown account type - skipping purge ⚠️")
                continue
            print(f"Keeping {keep_count} versions")

            # Process file by file
            for file in utils.get_project_files_with_versions(proj_instance.pk):

                filename = file.latest.name
                old_versions = file.versions

                # Sort by date (newest first)
                old_versions.sort(key=lambda i: i.last_modified, reverse=True)

                # Skip the newest N
                old_versions_to_purge = old_versions[keep_count:]

                # Debug print
                all_count = len(old_versions)
                topurge_count = len(old_versions_to_purge)
                print(
                    f'Purging {topurge_count} out of {all_count} old versions for "{filename}"...'
                )

                # Remove the N oldest
                for old_version in old_versions_to_purge:
                    # TODO: any way to batch those ? will probaby get slow on production
                    old_version._data.delete()
                    # TODO: audit ? take implementation from files_views.py:211

        print("done !")
