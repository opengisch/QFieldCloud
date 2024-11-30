from django.db import models
from django.db.models.fields.files import FieldFile
from django.core.files.storage import storages


class EmptyStorageNameError(Exception):
    def __init__(self, *args: object, instance: models.Model) -> None:
        message = f"Storage name is empty for {instance=}"
        super().__init__(message, *args)


class DynamicStorageFieldFile(FieldFile):
    def __init__(self, instance, field, name):
        super().__init__(instance, field, name)

        storage_name = instance._get_file_storage_name()
        if not storage_name:
            raise EmptyStorageNameError(instance=instance)

        self.storage = storages[storage_name]


class DynamicStorageFileField(models.FileField):
    attr_class = DynamicStorageFieldFile

    def pre_save(self, instance, add):
        storage_name = instance._get_file_storage_name()

        if not storage_name:
            raise EmptyStorageNameError(instance=instance)

        storage = storages[storage_name]

        self.storage = storage

        file = super().pre_save(instance, add)

        return file
