from django.apps import AppConfig

from qfieldcloud.core.patches import patch_allauth_email_filter


class CoreConfig(AppConfig):
    name = "qfieldcloud.core"

    def ready(self):
        from qfieldcloud.core import signals  # noqa

        patch_allauth_email_filter()
