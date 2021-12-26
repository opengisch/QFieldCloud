import json
from typing import Any, Dict, List, Union

from auditlog.models import LogEntry
from django.contrib.auth.models import User
from django_currentuser.middleware import get_current_authenticated_user


def audit(
    instance,
    action: LogEntry.Action,
    changes: Union[Dict[str, Any], List[Any], str] = None,
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

    actor_id = actor.pk if actor else None

    return LogEntry.objects.log_create(
        instance,
        action=action,
        changes=changes_json,
        actor_id=actor_id,
        remote_addr=remote_addr,
        additional_data=additional_data,
    )
