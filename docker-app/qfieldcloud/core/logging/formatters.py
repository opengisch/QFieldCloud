import json_log_formatter
from django.core.handlers.wsgi import WSGIRequest
from django.core.serializers.json import DjangoJSONEncoder


class JsonEncoder(DjangoJSONEncoder):
    def default(self, obj):
        return super().default(obj)


class CustomisedJSONFormatter(json_log_formatter.JSONFormatter):
    def to_json(self, record):
        """Converts record dict to a JSON string.
        It makes best effort to serialize a record (represents an object as a string)
        instead of raising TypeError if json library supports default argument.
        Note, ujson doesn't support it.
        Override this method to change the way dict is converted to JSON.
        """
        try:
            return self.json_lib.dumps(
                record, default=json_default, sort_keys=True, cls=JsonEncoder
            )
        # ujson doesn't support default argument and raises TypeError.
        except TypeError:
            return self.json_lib.dumps(record, cls=JsonEncoder)


def json_default(obj):
    if isinstance(obj, WSGIRequest):
        return str(obj)

    try:
        return obj.__dict__
    except AttributeError:
        return str(obj)
