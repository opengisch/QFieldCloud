import logging
import os
from logging import handlers

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


rotating_file_handler = handlers.RotatingFileHandler(
    filename=os.path.join("/log", "orchestrator.log"),
    mode="a",
    maxBytes=5 * 1024 * 1024,
    backupCount=2,
    encoding=None,
    delay=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[rotating_file_handler],
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
