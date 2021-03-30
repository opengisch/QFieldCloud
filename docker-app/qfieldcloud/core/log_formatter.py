import datetime
import json
import logging
import traceback

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


class CustomisedRequestHumanFormatter(logging.Formatter):
    def format(self, record):
        record.getMessage()
        extra = self.extra_from_record(record)

        created = extra.get("created")
        if created:
            created = datetime.datetime.fromtimestamp(created)

        request_headers = "\n"
        for header, value in extra.get("request_headers", {}).items():
            request_headers += f"    {header}: {value}\n"

        response_headers = "\n"
        for _key, (header, value) in extra.get("response_headers", {}).items():
            response_headers += f"    {header}: {value}\n"

        request_body = (
            extra.get("request_body", "NO_REQUEST_BODY") or "EMPTY_REQUEST_BODY"
        )
        if not isinstance(request_body, str):
            request_body = json.dumps(request_body, indent=2, cls=JsonEncoder)

        response_body = (
            extra.get("response_body", "NO_RESPONSE_BODY") or "EMPTY_RESPONSE_BODY"
        )
        if not isinstance(response_body, str):
            response_body = json.dumps(response_body, indent=2, cls=JsonEncoder)

        python_exception = ""
        if extra.get("exception"):
            exception = extra.get("exception")
            tb1 = traceback.TracebackException.from_exception(exception)
            exception_str = "    ".join(tb1.format())
            python_exception = f"""Exception (ERROR):
  {exception_str}
"""

        return f"""
================================================================================
| HTTP Request
================================================================================
Request: {extra.get("request_method", "UNKNOWN_REQUEST_METHOD")} {extra.get("request_path", "UNKNOWN_REQUEST_PATH")} {extra.get("status_code", "UNKNOWN_STATUS_CODE")}
Time: {created}; relative - {extra.get("relativeCreated", "UNKNOWN_RELATIVE_CREATED")}; runtime - {extra.get("run_time", "UNKNOWN_RUN_TIME")}
Context: PID #{extra.get("process", "UNKNOWN_PID")}; thread #{extra.get("thread", "UNKNOWN_THREAD")} ({extra.get("threadName", "UNKNOWN_THREAD_NAME")})
Request headers: {request_headers}
Request payload:
------------------------------------------------------------------------------S
{request_body}
------------------------------------------------------------------------------E
{python_exception}
Response headers: {response_headers}
Response payload:
------------------------------------------------------------------------------S
{response_body}
------------------------------------------------------------------------------E
        """

    def extra_from_record(self, record):
        """Returns `extra` dict you passed to logger.
        The `extra` keyword argument is used to populate the `__dict__` of
        the `LogRecord`.
        """
        return {attr_name: record.__dict__[attr_name] for attr_name in record.__dict__}


def json_default(obj):
    if isinstance(obj, WSGIRequest):
        return str(obj)

    try:
        return obj.__dict__
    except AttributeError:
        return str(obj)
