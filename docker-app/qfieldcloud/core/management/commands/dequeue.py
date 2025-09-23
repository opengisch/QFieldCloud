import logging
import signal
from time import sleep
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandParser
from django.db import connection, transaction
from django.db.models import Q
from qfieldcloud.core.models import Job
from worker_wrapper.wrapper import (
    DeltaApplyJobRun,
    JobRun,
    PackageJobRun,
    ProcessProjectfileJobRun,
    cancel_orphaned_workers,
)

SECONDS = 5


class GracefulKiller:
    alive = True

    def __init__(self) -> None:
        signal.signal(signal.SIGINT, self._kill)
        signal.signal(signal.SIGTERM, self._kill)

    def _kill(self, *_args: Any) -> None:
        self.alive = False


class Command(BaseCommand):
    help = "Dequeue QFieldCloud Jobs from the DB"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--single-shot", action="store_true", help="Don't run infinite loop."
        )

    def handle(
        self,
        *args: Any,
        single_shot: bool | None = None,
        **kwargs: Any,
    ) -> None:
        logging.info("Dequeue QFieldCloud Jobs from the DB")
        killer = GracefulKiller()

        while killer.alive:
            # the worker-wrapper caches outdated ContentType ids during tests since
            # the worker-wrapper and the tests reside in different containers
            if settings.DATABASES["default"]["NAME"].startswith("test_"):
                ContentType.objects.clear_cache()

            cancel_orphaned_workers()

            with connection.cursor() as cursor:
                # NOTE `pg_is_in_recovery` returns `FALSE` if connected to the master node
                cursor.execute("SELECT pg_is_in_recovery()")
                # there is no way `cursor.fetchone()` returns no rows, therefore ignore the type warning
                if cursor.fetchone()[0]:  # type: ignore
                    raise Exception(
                        "Expected `worker_wrapper` to be connected to the master DB node!"
                    )

            queued_job = None

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

                busy_projects_ids_qs = Job.objects.filter(
                    status__in=[
                        Job.Status.QUEUED,
                        Job.Status.STARTED,
                    ]
                ).values("project_id")

                # select all the pending jobs, that their project has no other active job or `locked_at` is not null
                jobs_qs = (
                    Job.objects.select_for_update(skip_locked=True)
                    .filter(status=Job.Status.PENDING)
                    .exclude(
                        Q(project_id__in=busy_projects_ids_qs)
                        # skip all projects that are currently locked, most probably because of file transfer
                        | Q(project__locked_at__isnull=False),
                    )
                    .order_by("created_at")
                )

                # each `worker_wrapper` or `dequeue.py` script can handle only one job and we handle the oldest
                queued_job = jobs_qs.first()

                # there might be no jobs in the queue
                if queued_job:
                    logging.info(f"Dequeued job {queued_job.id}, run!")
                    queued_job.status = Job.Status.QUEUED
                    queued_job.save(update_fields=["status"])

            if queued_job:
                self._run(queued_job)
                queued_job = None
            else:
                if single_shot:
                    break

                for _i in range(SECONDS):
                    if killer.alive:
                        cancel_orphaned_workers()
                        sleep(1)

            if single_shot:
                break

    def _run(self, job: Job) -> None:
        job_run_classes: dict[Job.Type, type[JobRun]] = {
            Job.Type.PACKAGE: PackageJobRun,
            Job.Type.DELTA_APPLY: DeltaApplyJobRun,
            Job.Type.PROCESS_PROJECTFILE: ProcessProjectfileJobRun,
        }

        if job.type in job_run_classes:
            job_run_class = job_run_classes[job.type]
        else:
            raise NotImplementedError(f"Unknown job type {job.type}")

        job_run = job_run_class(job.id)
        job_run.run()
