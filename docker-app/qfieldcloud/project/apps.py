from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "qfieldcloud.project"

    def ready(self):
        import qfieldcloud.project.signals  # noqa
