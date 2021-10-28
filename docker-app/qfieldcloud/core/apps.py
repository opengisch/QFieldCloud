from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "qfieldcloud.core"

    def ready(self):
        from qfieldcloud.core import signals  # noqa
