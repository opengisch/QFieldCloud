import logging
import os

import sentry_sdk
from db_utils import JobStatus, get_job_row, update_job
from redis import Redis
from rq import Connection, Worker
from sentry_sdk.integrations.rq import RqIntegration

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[RqIntegration()],
    server_name=os.environ.get("QFIELDCLOUD_HOST"),
    attach_stacktrace="on",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)


def handle_exception(job, *exc_info):
    try:
        job_row = get_job_row(job.id)

        # TODO this is highly questionable behavior. Why do we have error anyway?
        # It lies on the assumption that the FINISHED status is set once we are sure we are done.
        # This is the case for exports and delta application.
        if job_row["status"] != JobStatus.FINISHED.value:
            update_job(job.id, JobStatus.FAILED)
        else:
            logging.info(
                "No need to update the current job status as it already finished"
            )
    except Exception as err:
        logging.critical("Failed to handle exception: ", str(err))


with Connection():
    redis = Redis(
        host=os.environ.get("REDIS_HOST"),
        password=os.environ.get("REDIS_PASSWORD"),
        port=6379,
    )

    qs = ["delta", "export"]

    w = Worker(qs, connection=redis, exception_handlers=handle_exception)
    w.work()
