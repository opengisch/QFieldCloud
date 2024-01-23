import psycopg2
from django.conf import settings
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


class GeodbConnection:
    def __init__(self):
        pass

    def __enter__(self):
        host = settings.GEODB_HOST
        port = settings.GEODB_PORT

        # If geodb is running on the same machine we connect trough
        # the internal docker net
        if host == "geodb":
            port = 5432

        self.connection = psycopg2.connect(
            dbname=settings.GEODB_DB,
            user=settings.GEODB_USER,
            password=settings.GEODB_PASSWORD,
            host=host,
            port=port,
        )

        return self.connection

    def __exit__(self, type, value, traceback):
        self.connection.close()


def geodb_is_running():
    """Check the connection to the geodb"""

    try:
        with GeodbConnection():
            pass
    except psycopg2.Error:
        return False

    return True


def create_role_and_db(geodb):
    """Create role and db.
    This function is automatically called when a Geodb object is created
    """

    with GeodbConnection() as conn:
        # CREATE DATABASE cannot run inside a transaction block
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        cur = conn.cursor()

        cur.execute(
            sql.SQL(
                """
            CREATE ROLE {} WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            INHERIT
            NOREPLICATION
            CONNECTION LIMIT 5
            PASSWORD %s;
            """
            ).format(sql.Identifier(geodb.username)),
            (geodb.password,),
        )

        cur.execute(
            sql.SQL(
                """
            CREATE DATABASE {}
            WITH
            OWNER = %s
            TEMPLATE = template_postgis
            ENCODING = 'UTF8'
            CONNECTION LIMIT = 5;
            """
            ).format(sql.Identifier(geodb.dbname)),
            (geodb.username,),
        )

    result = {
        "hostname": geodb.hostname,
        "port": geodb.port,
        "username": geodb.username,
        "dbname": geodb.dbname,
        "password": geodb.password,
    }
    return result


def delete_db_and_role(dbname, username):
    with GeodbConnection() as conn:
        # DROP DATABASE cannot be executed inside a transaction block
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        cur = conn.cursor()

        cur.execute(
            sql.SQL(
                """
            DROP DATABASE IF EXISTS {};
            """
            ).format(sql.Identifier(dbname))
        )

        cur.execute(
            sql.SQL(
                """
            DROP ROLE IF EXISTS {};
            """
            ).format(sql.Identifier(username))
        )


def get_db_size(geodb):
    """Return the size of the database in bytes"""

    with GeodbConnection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT pg_database_size(%s);", (geodb.dbname,))
        return cur.fetchone()[0]
