import logging
from time import sleep

from django.core.management.base import BaseCommand
from qfieldcloud.core.models import Job, Project
from qfieldcloud.core.utils2 import queue
from qfieldcloud.core.utils2.db import use_test_db_if_exists

SECONDS = 1


class Command(BaseCommand):
    help = "Dequeue QFieldCloud Jobs from the DB"

    def handle(self, *args, **options):
        logging.info("Dequeue QFieldCloud Jobs from the DB")

        while True:
            with use_test_db_if_exists():
                jobs_count = 0
                for job in Job.objects.filter(
                    status=Job.Status.PENDING, project__status=Project.Status.IDLE
                ):
                    logging.info(f"Start job {job.id}")
                    jobs_count += 1
                    queue.start_job(job)

                if jobs_count == 0:
                    for _i in range(SECONDS):
                        sleep(1)
