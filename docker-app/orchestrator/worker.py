import logging
import os

import sentry_sdk
from qfieldcloud.core.models import Job
from qfieldcloud.core.utils2.db import use_test_db_if_exists
from redis import Redis
from rq import Connection, Worker
from sentry_sdk.integrations.rq import RqIntegration

logger = logging.getLogger(__name__)

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[RqIntegration()],
    server_name=os.environ.get("QFIELDCLOUD_HOST"),
    attach_stacktrace="on",
)


def handle_exception(job, *exc_info):
    logger.warning(f"Exception {exc_info}")

    try:

        with use_test_db_if_exists():
            job = Job.objects.get(pk=job.id)

            # TODO this is highly questionable behavior. Why do we have error anyway?
            # It lies on the assumption that the FINISHED status is set once we are sure we are done.
            # This is the case for exports and delta application.
            if job.status != Job.Status.FINISHED:
                job.status = Job.Status.FAILED
                job.save()
            else:
                logger.info(
                    "No need to update the current job status as it already finished"
                )
    except Exception as err:
        logger.critical("Failed to handle exception: ", str(err))


with Connection():
    redis = Redis(
        "redis",
        password=os.environ.get("REDIS_PASSWORD"),
        port=6379,
    )

    qs = ["delta", "export", "process_projectfile"]

    w = Worker(qs, connection=redis, exception_handlers=handle_exception)
    w.work()
