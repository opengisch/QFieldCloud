import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from django.db import models, transaction

Model = TypeVar("Model", bound=models.Model)


def get_or_none(
    model: type[Model],
    queryset: models.QuerySet[Model] | models.Manager[Model] | None = None,
    **kwargs,
) -> Model | None:
    try:
        if queryset is None:
            queryset = model.objects

        return queryset.get(**kwargs)
    except model.DoesNotExist:
        return None


@contextmanager
def advisory_lock(lock_name: str, lock_timeout: str = "20s") -> Iterator[None]:
    """
    Makes transactions that name the same resource run one at a time.

    Reserves a name rather than locking table rows. The first transaction to
    claim a name holds it until it ends; others wait. Only works if every code
    path touching the resource uses the same name.

    See https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS

    Args:
        lock_name: identifier of the guarded resource, e.g. `billing:account:42`.
        lock_timeout: how long to wait before giving up, as a PostgreSQL interval.

    Raises:
        RuntimeError: if called outside a transaction, where the lock would be
            released immediately and protect nothing.
        django.db.utils.OperationalError: if `lock_timeout` expires (pgcode `55P03`).

    Note:
        The lock is released when the outermost transaction ends, which may be
        later than the exit of this block.
    """
    connection = transaction.get_connection()

    if not connection.in_atomic_block:
        raise RuntimeError(
            "`advisory_lock` must be used inside `transaction.atomic()`."
        )

    lock_id = zlib.crc32(lock_name.encode())

    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [lock_timeout])
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])

    yield
