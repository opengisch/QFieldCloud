import json
import os
from enum import Enum
from typing import Any, Dict

import psycopg2
from psycopg2 import connect, sql
from psycopg2.extras import DictCursor


class JobStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    STARTED = "started"
    FINISHED = "finished"
    # STOPPED = "stopped" # NOT IN USE
    FAILED = "failed"


def get_django_db_connection():
    """Connect to the Django db."""
    dbname = os.environ.get("POSTGRES_DB")

    try:
        conn = connect(
            dbname=dbname,
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD"),
            host=os.environ.get("POSTGRES_HOST"),
            port=os.environ.get("POSTGRES_PORT"),
        )
    except psycopg2.OperationalError:
        return None

    return conn


def get_job_row(job_id: str) -> Dict[str, Any]:
    conn = get_django_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        """
            SELECT *
            FROM core_job
            WHERE
              id = %s
        """,
        (job_id,),
    )
    conn.commit()

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row


def update_job(job_id, status, exportlog=None, output=None):
    """Set the deltafile status and output into the database record """

    update_data = {
        "status": status.value,
    }

    if exportlog is not None:
        update_data["exportlog"] = json.dumps(exportlog)

    if output is not None:
        update_data["output"] = output

    sql_query = sql.SQL(
        """
            UPDATE core_job
            SET
                updated_at = now(),
                {data}
            WHERE id = {id}
        """
    ).format(
        data=sql.SQL(", ").join(
            sql.Composed([sql.Identifier(k), sql.SQL(" = "), sql.Placeholder(k)])
            for k in update_data.keys()
        ),
        id=sql.Placeholder("id"),
    )
    update_data.update(id=job_id)

    conn = get_django_db_connection()
    with conn.cursor() as cur:
        cur.execute(sql_query, update_data)
        conn.commit()
        conn.close()
