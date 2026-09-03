from typing import Any


def get_stored_value(instance: Any, field_name: str) -> Any:
    """The value currently stored in the database for `field_name` on `instance`.

    Returns `None` when `instance` has never been saved. Use it to compare the
    stored value against the in-memory one, for example to act only when a field is
    actually being changed. Be cautious when using with FK fields.
    """
    if instance._state.adding or instance.pk is None:
        return None

    return (
        type(instance)
        ._base_manager.filter(pk=instance.pk)
        .values_list(field_name, flat=True)
        .first()
    )
