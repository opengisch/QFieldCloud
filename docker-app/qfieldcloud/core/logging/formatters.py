from datetime import datetime

import json_log_formatter
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.serializers.json import DjangoJSONEncoder


class JsonEncoder(DjangoJSONEncoder):
    def default(self, obj):
        return super().default(obj)


class CustomisedJSONFormatter(json_log_formatter.JSONFormatter):
    def json_record(self, message, extra, record):
        """Prepares a JSON payload which will be logged.

        Override this method to change JSON log format.

        :param message: Log message, e.g., `logger.info(msg='Sign up')`.
        :param extra: Dictionary that was passed as `extra` param
            `logger.info('Sign up', extra={'referral_code': '52d6ce'})`.
        :param record: `LogRecord` we got from `JSONFormatter.format()`.
        :return: Dictionary which will be passed to JSON lib.

        """
        if "ts" not in extra:
            extra["ts"] = datetime.utcnow()

        # Include builtins
        extra["level"] = record.levelname
        extra["name"] = record.name
        extra["message"] = message
        extra["request_id"] = getattr(record, "request_id", None)
        extra["filename"] = record.filename
        extra["lineno"] = record.lineno
        extra["thread"] = record.thread
        extra["source"] = settings.LOGGER_SOURCE

        if record.exc_info:
            extra["exc_info"] = self.formatException(record.exc_info)

        return extra

    def to_json(self, record):
        """Converts record dict to a JSON string.
        It makes best effort to serialize a record (represents an object as a string)
        instead of raising TypeError if json library supports default argument.
        Note, ujson doesn't support it.
        Override this method to change the way dict is converted to JSON.
        """
        try:
            return self.json_lib.dumps(
                record, default=json_default, cls=JsonEncoder, separators=(",", ":")
            )
        # ujson doesn't support default argument and raises TypeError.
        except TypeError:
            return self.json_lib.dumps(record, cls=JsonEncoder, separators=(",", ":"))


def json_default(obj):
    if isinstance(obj, WSGIRequest):
        return str(obj)

    try:
        return obj.__dict__
    except AttributeError:
        return str(obj)
