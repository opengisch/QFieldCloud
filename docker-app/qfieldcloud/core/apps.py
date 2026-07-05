from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "qfieldcloud.core"

    def ready(self):
        from qfieldcloud.core import signals  # noqa

        # Monkey patch DEFAULT_MAX_NUM to a higher value to prevent saving
        # of large formsets from erroring out. This monkey patch should be
        # removed once this is configurable as a setting in Django.
        # See QF-8530.
        import django.forms.formsets

        django.forms.formsets.DEFAULT_MAX_NUM = 5000
