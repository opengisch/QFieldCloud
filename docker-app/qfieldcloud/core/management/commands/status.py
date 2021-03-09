import time

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

        job = utils.check_orchestrator_status()
        results["orchestrator"] = "ok"
        # Wait for the worker to finish
        for _ in range(30):
            time.sleep(2)
            if job.get_status() == "finished":
                if _ >= 10:
                    results["orchestrator"] = "slow"
                else:
                    results["orchestrator"] = "ok"
                break
            if job.get_status() == "failed":
                break

        if not job.get_status() in ["finished"]:
            results["orchestrator"] = "error"

        for result in results:
            if not results[result] in ["slow", "ok"]:
                self.stdout.write(
                    self.style.ERROR(
                        "Something doesn't work correctly: {}".format(results)
                    )
                )
                return

        self.stdout.write(
            self.style.SUCCESS("Everything seems to work properly: {}".format(results))
        )
