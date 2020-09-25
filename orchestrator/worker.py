import os
import logging
from logging import handlers

import sentry_sdk
from sentry_sdk.integrations.rq import RqIntegration

from rq import Connection, Worker
from redis import Redis


def env():
    """Read env file and return a dict with the variables"""

    environment = {}
    with open('../.env') as f:
        for line in f:
            if line.strip():
                splitted = line.rstrip().split('=', maxsplit=1)
                environment[splitted[0]] = splitted[1]

    return environment


sentry_sdk.init(
    dsn=env().get('SENTRY_DSN', ''),
    integrations=[RqIntegration()],
    server_name=env().get('QFIELDCLOUD_HOST'),
    attach_stacktrace='on',
)


rotating_file_handler = handlers.RotatingFileHandler(
    filename=os.path.join(
        env().get('LOG_DIRECTORY', ''),
        'orchestrator.log'),
    mode='a',
    maxBytes=5 * 1024 * 1024,
    backupCount=2,
    encoding=None,
    delay=False
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[rotating_file_handler],
)

with Connection():
    redis = Redis(
        password=env().get('REDIS_PASSWORD'),
    )

    qs = ['delta', 'export']

    w = Worker(qs, connection=redis)
    w.work()
