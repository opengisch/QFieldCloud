import logging
import os
from time import sleep, time

import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

TIMEOUT = 30
INTERVAL = 2


def wait_for_postgres():
    logger.info("Waiting for postgres...")
    config = {
        "dbname": os.environ.get("POSTGRES_DB"),
        "user": os.environ.get("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD"),
        "host": os.environ.get("POSTGRES_HOST"),
        "port": os.environ.get("POSTGRES_PORT"),
        "sslmode": os.environ.get("POSTGRES_SSLMODE"),
        "connect_timeout": TIMEOUT,
    }
    start_time = time()
    while time() - start_time < TIMEOUT:
        try:
            conn = psycopg2.connect(**config)
            logger.info("Postgres is ready! ✨ 💅")
            conn.close()
            return True
        except psycopg2.OperationalError as error:
            if time() - start_time < TIMEOUT:
                logger.info(
                    f"Postgres isn't ready.\npsycopg2 {type(error).__name__}\n{error}\nWaiting for {INTERVAL} second(s)..."
                )
                sleep(INTERVAL)
            else:
                logger.error(
                    f"Postgres never responded in {TIMEOUT} seconds.\npsycopg2 {type(error).__name__}\n{error}"
                )

    logger.error(f"We could not connect to Postgres within {TIMEOUT} seconds.")

    return False


wait_for_postgres()
