import json
import os
from enum import Enum
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2 import connect, sql
from psycopg2.extras import DictCursor, Json


class DeltaStatus(Enum):
    PENDING = "pending"
    STARTED = "started"
    APPLIED = "applied"
    CONFLICT = "conflict"
    NOT_APPLIED = "not_applied"
    ERROR = "error"
    IGNORED = "ignored"
    UNPERMITTED = "unpermitted"


class JobStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    STARTED = "started"
    FINISHED = "finished"
    # STOPPED = "stopped" # NOT IN USE
    FAILED = "failed"


def get_django_db_connection():
    """Connect to the Django db."""
    try:
        dbname = os.environ.get("POSTGRES_DB")
        test_dbname = f"test_{dbname}"
        conn_dbname = dbname

        conn = connect(
            dbname="template1",
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD"),
            host=os.environ.get("POSTGRES_HOST"),
            port=os.environ.get("POSTGRES_PORT"),
        )
        cur = conn.cursor()

        cur.execute(
            """
                SELECT datname
                FROM pg_database
                WHERE datname = %s
            """,
            (test_dbname,),
        )

        if cur.fetchone():
            conn_dbname = test_dbname

        conn = connect(
            dbname=conn_dbname,
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
            FROM core_job j
            LEFT JOIN core_applyjob daj ON daj.job_ptr_id = j.id
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


def get_deltas_to_apply_list(job_id: str) -> Dict[str, Any]:
    conn = get_django_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        """
            SELECT array_agg(delta_id) as delta_ids
            FROM core_applyjobdelta dajd
            WHERE
              apply_job_id = %s
        """,
        (job_id,),
    )
    conn.commit()

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row["delta_ids"]


def update_deltas(
    job_id: str,
    delta_ids: List[str],
    status: DeltaStatus,
    feedback: Optional[str] = None,
) -> List[Dict]:
    update_applyjobdelta_data = {
        "status": status.value,
        "feedback": Json(feedback),
    }
    sql_applyjobdelta_query = sql.SQL(
        """
            UPDATE core_applyjobdelta
            SET
                -- updated_at = now(),
                {data}
            WHERE TRUE
                AND apply_job_id = {job_id}
                AND delta_id IN ({delta_ids})
        """
    ).format(
        job_id=sql.Literal(job_id),
        data=sql.SQL(", ").join(
            sql.Composed([sql.Identifier(k), sql.SQL(" = "), sql.Placeholder(k)])
            for k in update_applyjobdelta_data.keys()
        ),
        delta_ids=sql.SQL(", ").join(
            map(lambda uuid: sql.Literal(str(uuid)), delta_ids)
        ),
    )

    update_delta_data = {
        "last_status": status.value,
        "last_feedback": Json(feedback),
    }

    sql_delta_query = sql.SQL(
        """
            UPDATE core_delta
            SET
                updated_at = now(),
                {data}
            WHERE
                id IN ({delta_ids})
            RETURNING *
        """
    ).format(
        data=sql.SQL(", ").join(
            sql.Composed([sql.Identifier(k), sql.SQL(" = "), sql.Placeholder(k)])
            for k in update_delta_data.keys()
        ),
        delta_ids=sql.SQL(", ").join(
            map(lambda uuid: sql.Literal(str(uuid)), delta_ids)
        ),
    )

    conn = get_django_db_connection()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql_applyjobdelta_query, update_applyjobdelta_data)
        cur.execute(sql_delta_query, update_delta_data)
        deltas = cur.fetchall()
        conn.commit()
        conn.close()

    return deltas
