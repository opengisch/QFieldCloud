from django.core.management.base import BaseCommand, CommandError
from qfieldcloud.core.models import WorkerPool


class Command(BaseCommand):
    help = """
        Create the global worker pool and print its credential.
        Usage: python manage.py createglobalworkerpool --name=global
    """

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str, default="global")
        parser.add_argument(
            "--new-credential",
            action="store_true",
            help="Replace the credential of the existing global pool, running workers stop working.",
        )

    def handle(self, *args, **options):
        pool = WorkerPool.objects.filter(organization__isnull=True).first()

        if pool and not options["new_credential"]:
            raise CommandError(
                "The global worker pool already exists, use --new-credential to replace its credential."
            )

        if not pool:
            pool = WorkerPool(name=options["name"])

        credential = pool.generate_credential()
        pool.save()

        self.stdout.write(credential)
