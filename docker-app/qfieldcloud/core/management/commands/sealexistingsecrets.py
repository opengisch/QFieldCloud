from django.core.management.base import BaseCommand
from django.db import transaction
from qfieldcloud.core.models import Secret


class Command(BaseCommand):
    help = """
        Seal the secrets that have no readable sealed value yet for the pool of their owner.
        Run it after the pools have registered their keys, it can safely be run again.
        Usage: python manage.py sealexistingsecrets
    """

    def handle(self, *args, **options):
        sealed = 0
        skipped = 0

        for secret in Secret.objects.select_related(
            "project__owner", "organization"
        ).iterator():
            if not secret.needs_reentering:
                continue

            with transaction.atomic():
                secret.seal_value()

            if secret.needs_reentering:
                skipped += 1
            else:
                sealed += 1

        self.stdout.write(f"Sealed {sealed}, skipped {skipped} without a pool key.")
