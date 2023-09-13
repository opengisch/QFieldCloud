import json
from typing import Any

from auditlog.models import LogEntry
from django.contrib.auth.models import AnonymousUser, User
from django_currentuser.middleware import get_current_authenticated_user


def audit(
    instance,
    action: LogEntry.Action,
    changes: dict[str, Any] | list[Any] | str | None = None,
    actor: User = None,
    remote_addr: str = None,
    additional_data: Any = None,
):
    changes_json = None

    try:
        if changes is not None:
            changes_json = json.dumps(changes)
    except Exception:
        changes_json = json.dumps(str(changes))

    if actor is None:
        actor = get_current_authenticated_user()
    elif isinstance(actor, AnonymousUser):
        actor = None

    actor_id = actor.pk if actor else None

    return LogEntry.objects.log_create(
        instance,
        action=action,
        changes=changes_json,
        actor_id=actor_id,
        remote_addr=remote_addr,
        additional_data=additional_data,
    )
