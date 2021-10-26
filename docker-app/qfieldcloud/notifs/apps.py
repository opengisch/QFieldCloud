from django.apps import AppConfig


class NotifsConfig(AppConfig):
    name = "qfieldcloud.notifs"
    verbose_name = "Notifs"

    def ready(self):
        from . import signals  # noqa
