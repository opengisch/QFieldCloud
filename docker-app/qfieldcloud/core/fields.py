from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from django.core.files.storage import Storage, storages
from django.db import models
from django.db.models.fields.files import FieldFile, ImageField, ImageFieldFile
from django.utils.functional import cached_property


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

        self._original_storage = self.storage

    @cached_property
    def storage(self) -> Storage:  # type: ignore
        """Get the storage backend instance based on the storage name returned by the model instance implementation of `_get_file_storage_name`.

        Instead of using the `storage` attribute from the base class `FieldFile`, we override it to dynamically determine the storage based on the model instance.
        The other option would be to calculate the `storage` attribute in the constructor, but it would require three database queries to get the storage name for each instance of the class, which is not efficient.

        Having this as a cached property allows us to calculate the storage only once per instance, which is more efficient.
        """
        # NOTE if the model is not saved yet, there is a chance that it was instantiated without values
        # for the foreign keys. In some models, e.g. `filestorage.FileVersion`, calling `_get_file_storage_name`
        # requires a foreign key value. Therefore we return the `default` storage for those cases.
        try:
            storage_name = self.instance._get_file_storage_name()  # type: ignore
        except Exception:
            if self.instance._state.adding:
                storage_name = "default"
            else:
                raise

        if not storage_name:
            raise EmptyStorageNameError(instance=self.instance)

        return storages[storage_name]


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


class QfcImageFile(ImageFieldFile):
    field: QfcImageField  # type: ignore

    @property
    def public_url(self) -> str | None:
        return self.field.download_url(self)


class QfcImageField(ImageField):
    attr_class = QfcImageFile

    def __init__(
        self,
        verbose_name: str | None = None,
        name: str | None = None,
        download_from: Callable[[models.Model, QfcImageFile | None], str | None]
        | None = None,
        **kwargs,
    ) -> None:
        self.download_from = download_from
        super().__init__(verbose_name, name, **kwargs)

    def download_url(self, value: QfcImageFile | None) -> str | None:
        if value and self.download_from:
            return self.download_from(value.instance, value)
        else:
            return None
