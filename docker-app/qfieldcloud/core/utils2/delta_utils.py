from typing import Any, Iterable
from uuid import UUID


def generate_deltafile(
    deltas: Iterable[dict[str, Any]],
    project_id: UUID,
    id: UUID = UUID("111111111-1111-1111-1111-11111111111"),
) -> dict[str, Any]:
    """Returns a deltafile-structured dictionary with the given deltas.
    The given deltas must be an iterable with at least one element.

    Args:
        deltas: deltas in the deltafile
        project_id: project ID
        id: deltafile UUID
    """
    deltas = list(deltas)
    deltafile = {
        "deltas": deltas,
        "files": [],
        "id": id,
        "project": project_id,
        "version": "1.0",
    }

    return deltafile
