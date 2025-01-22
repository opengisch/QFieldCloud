from __future__ import annotations

from typing import Protocol, cast, Any
from django.db import models
from django.db.models.fields.files import FieldFile
from django.core.files.storage import storages


class FileStorageNameModelProtocol(Protocol):
    def _get_file_storage_name(self) -> str: ...


class FileStorageNameModelProtocolMetaclass(type(models.Model), type(Protocol)):  # type: ignore
    """Required to prevent metaclass error: Metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of the metaclasses of all its bases"""


class ModelWithDynamicStorage(
    models.Model,
    FileStorageNameModelProtocol,
    metaclass=FileStorageNameModelProtocolMetaclass,
):
    class Meta:
        abstract = True


class EmptyStorageNameError(Exception):
    def __init__(self, *args: object, instance: models.Model) -> None:
        message = f"Storage name is empty for {instance=}"
        super().__init__(message, *args)


class DynamicStorageFieldFile(FieldFile):
    """The file with a dynamic storage - it is determined by the instance of the model.

    Read more: https://docs.djangoproject.com/en/5.1/ref/models/fields/#filefield-and-fieldfile

    See also:
        - DynamicStorageFileField
    """

    def __init__(
        self, instance: models.Model, field: DynamicStorageFileField, name: str
    ):
        instance = cast(ModelWithDynamicStorage, instance)

        super().__init__(instance, field, name)

        storage_name = instance._get_file_storage_name()
        if not storage_name:
            raise EmptyStorageNameError(instance=instance)

        self.storage = storages[storage_name]


class DynamicStorageFileField(models.FileField):
    """The field for storing files with a dynamic storage - it is determined by the instance of the model.

    Read more: https://docs.djangoproject.com/en/5.1/ref/models/fields/#filefield-and-fieldfile

    See also:
        - DynamicStorageFieldFile
    """

    attr_class = DynamicStorageFieldFile

    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        model_instance = cast(ModelWithDynamicStorage, model_instance)

        storage_name = model_instance._get_file_storage_name()

        if not storage_name:
            raise EmptyStorageNameError(instance=model_instance)

        storage = storages[storage_name]

        self.storage = storage

        file = super().pre_save(model_instance, add)

        return file
