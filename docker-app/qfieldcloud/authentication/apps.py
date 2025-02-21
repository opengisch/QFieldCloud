from django.apps import AppConfig


class AuthConfig(AppConfig):
    name = "qfieldcloud.authentication"
    initialized = False

    @classmethod
    def initialize(cls):
        """
        Initialize authentication.
        This method is re-entrant and can be called multiple times.
        """

        if cls.initialized:
            return

        cls.initialized = True

        from .conf import settings  # noqa

    def ready(self):
        self.initialize()
