import logging

from django.http import HttpRequest


def skip_logging(func):
    def wrapper(instance, *args, **kwargs):
        request = instance.request

        if not isinstance(request, HttpRequest):
            request = request._request

        request.skip_logging = True

        return func(instance, *args, **kwargs)

    return wrapper


class SkipLoggingFilter(logging.Filter):
    def filter(self, record):
        return not getattr(record, "skip_logging", False)

    def extra_from_record(self, record):
        """Returns `extra` dict you passed to logger.
        The `extra` keyword argument is used to populate the `__dict__` of
        the `LogRecord`.
        """
        return {attr_name: record.__dict__[attr_name] for attr_name in record.__dict__}
