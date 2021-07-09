import logging
from time import sleep

from django.core.management.base import BaseCommand
from qfieldcloud.core.models import Job, Project
from qfieldcloud.core.utils2 import queue

SECONDS = 10


class Command(BaseCommand):
    help = "Dequeue QFieldCloud Jobs from the DB"

    def handle(self, *args, **options):
        logging.info("Dequeue QFieldCloud Jobs from the DB")

        while True:
            jobs_count = 0
            for job in Job.objects.filter(
                status=Job.Status.PENDING, project__status=Project.Status.IDLE
            ):
                logging.info(f"Start job {job.id}")
                jobs_count += 1
                queue.start_job(job)

            if jobs_count == 0:
                logging.info(f"No jobs found, sleep for {SECONDS} seconds")
                for _i in range(SECONDS):
                    sleep(1)
