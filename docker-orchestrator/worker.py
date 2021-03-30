import logging
import os

import sentry_sdk
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

with Connection():
    redis = Redis(
        host=os.environ.get("REDIS_HOST"),
        password=os.environ.get("REDIS_PASSWORD"),
        port=6379,
    )

    qs = ["delta", "export"]

    w = Worker(qs, connection=redis)
    w.work()
