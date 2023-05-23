from django.conf import settings
from django.core.management.base import BaseCommand
from qfieldcloud.core import geodb_utils, utils


class Command(BaseCommand):
    help = "Check qfieldcloud status"

    def handle(self, *args, **options):
        results = {}

        results["redis"] = "ok"
        # Check if redis is visible
        if not utils.redis_is_running():
            results["redis"] = "error"

        results["geodb"] = "ok"
        # Check geodb
        if not geodb_utils.geodb_is_running():
            results["geodb"] = "error"

        results["storage"] = "ok"
        # Check if bucket exists (i.e. the connection works)
        try:
            s3_client = utils.get_s3_client()
            s3_client.head_bucket(Bucket=settings.STORAGE_BUCKET_NAME)
        except Exception:
            results["storage"] = "error"

        self.stdout.write(
            self.style.SUCCESS(f"Everything seems to work properly: {results}")
        )
