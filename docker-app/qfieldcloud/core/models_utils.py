from typing import Any


def get_stored_value(instance: Any, field_name: str) -> Any:
    """The value currently stored in the database for `field_name` on `instance`.

    Returns `None` when `instance` has never been saved. Use it to compare the
    stored value against the in-memory one, for example to act only when a field is
    actually being changed.

    If `field_name` is a foreign key, you get the stored id back, not the related object.
    For example compare it against `instance.owner_id`. `instance.owner` is a model object,
    so it will not equal an id, and touching it can trigger a query.
    """
    if instance._state.adding or instance.pk is None:
        return None

    return (
        type(instance)
        ._base_manager.filter(pk=instance.pk)
        .values_list(field_name, flat=True)
        .first()
    )
