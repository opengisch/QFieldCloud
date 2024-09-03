from django.core.management.base import BaseCommand
from qfieldcloud.core import utils


class Command(BaseCommand):
    help = "Check qfieldcloud status"

    def handle(self, *args, **options):
        results = {}
        results["storage"] = "ok"
        # Check if bucket exists (i.e. the connection works)
        try:
            utils.get_s3_bucket()
        except Exception:
            results["storage"] = "error"

        self.stdout.write(
            self.style.SUCCESS(f"Everything seems to work properly: {results}")
        )
