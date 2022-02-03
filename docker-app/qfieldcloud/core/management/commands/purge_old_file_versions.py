from django.core.management.base import BaseCommand, CommandError
from qfieldcloud.core.models import Project
from qfieldcloud.core.utils2 import storage


class Command(BaseCommand):
    """Runs purge_old_file_versions as a management command"""

    help = storage.purge_old_file_versions.__doc__

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
            storage.purge_old_file_versions(proj_instance)

        print("done !")
