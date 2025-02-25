from django.apps import AppConfig


class FileStorageConfig(AppConfig):
    name = "qfieldcloud.filestorage"
    verbose_name = "FileStorage"

    def ready(self):
        from . import signals  # noqa
