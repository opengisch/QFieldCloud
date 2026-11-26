from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "qfieldcloud.core"

    def ready(self):
        from qfieldcloud.core import signals  # noqa
        from qfieldcloud.core.templatetags.datetime_tooltip import (
            patch_admin_datetime_display,
        )

        patch_admin_datetime_display()
