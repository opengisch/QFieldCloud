from typing import Any

from auditlog.models import LogEntry
from django.contrib.auth.models import AnonymousUser, User
from django_currentuser.middleware import get_current_authenticated_user


def audit(
    instance,
    action: LogEntry.Action,
    changes: dict[str, Any] | list[Any] | str | None = None,
    actor: User | None = None,
    remote_addr: str | None = None,
    additional_data: Any | None = None,
):
    if actor is None:
        actor = get_current_authenticated_user()
    elif isinstance(actor, AnonymousUser):
        actor = None

    actor_id = actor.pk if actor else None

    return LogEntry.objects.log_create(
        instance,
        action=action,
        changes=changes,
        actor_id=actor_id,
        remote_addr=remote_addr,
        additional_data=additional_data,
    )
