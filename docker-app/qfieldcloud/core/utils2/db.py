from typing import Type, TypeVar

from django.db import models

Model = TypeVar("Model", bound=models.Model)


def get_or_none(
    model: Type[Model],
    queryset: models.QuerySet[Model] | models.Manager[Model] | None = None,
    **kwargs,
) -> Model | None:
    try:
        if queryset is None:
            queryset = model.objects

        return queryset.get(**kwargs)
    except model.DoesNotExist:
        return None
