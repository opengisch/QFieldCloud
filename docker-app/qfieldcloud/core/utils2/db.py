import logging

from django.conf import settings
from django.db import connection, connections

logger = logging.getLogger(__name__)


class use_test_db_if_exists:
    """
    Context manager that updates django database settings to use the test db if it exists.
    Will be ignored if debug is False
    """

    def __enter__(self):
        # save initial db name
        if not settings.DEBUG:
            return
        self._init_dbname = settings.DATABASES["default"]["NAME"]

        # updating the database name to use the test database
        test_dbname = f"test_{self._init_dbname}"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT datname FROM pg_database WHERE datname = %s", [test_dbname]
            )
            if cursor.fetchone():
                settings.DATABASES["default"]["NAME"] = test_dbname
                logger.info(f'Using DB {settings.DATABASES["default"]["NAME"]}')
                self._invalidate()

    def __exit__(self, exc_type, exc_value, traceback):
        # restore initial db name
        if not settings.DEBUG:
            return

        if settings.DATABASES["default"]["NAME"] != self._init_dbname:
            logger.info(f'Restoring DB {settings.DATABASES["default"]["NAME"]}')

        self._invalidate()

    def _invalidate(self):
        # invalidate connections so they are recreated with the modified dbname
        for conn in connections.all():
            conn.close()
