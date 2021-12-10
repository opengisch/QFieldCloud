"""
Middleware to log all requests and responses.
Uses a logger configured by the name of django.request
to log all requests and responses according to configuration
specified for django.request.

inspired by https://gist.github.com/SehgalDivij/1ca5c647c710a2c3a0397bce5ec1c1b4
"""
import json

# import json
import logging
import os
import socket
import time

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("qfieldcloud.request_response_log")

MAX_RESPONSE_BODY_LENGTH = 1000
CENSOR_DATA_KEYS = [
    "password",
    "token",
    "Authorization",
]


class RequestResponseLogMiddleware(MiddlewareMixin):
    """Request Logging Middleware."""

    def __init__(self, *args, **kwargs):
        """Constructor method."""
        super().__init__(*args, **kwargs)

    def process_request(self, request):
        """Set Request Start Time to measure time taken to service request."""
        request.start_time = time.time()

    def extract_log_info(self, request, response=None, exception=None):
        """Extract appropriate log info from requests/responses/exceptions."""
        log_data = {
            "skip_logging": getattr(request, "skip_logging", False),
            "remote_address": request.META["REMOTE_ADDR"],
            "server_hostname": socket.gethostname(),
            "request_method": request.method,
            "files": tuple(dict(request.FILES).keys()),
            "request_path": request.get_full_path(),
            "request_headers": {**request.headers},
            "run_time": time.time() - request.start_time,
        }

        log_data["request_headers"] = self.censor_sensitive_data(
            log_data["request_headers"]
        )

        if request.method in ["PUT", "POST", "PATCH"]:
            if request.content_type == "application/octet-stream":
                log_data["request_body"] = None
            else:
                log_data["request_body"] = request.POST
                log_data["request_body"] = self.censor_sensitive_data(
                    log_data["request_body"]
                )

        if hasattr(request, "exception"):
            log_data["exception"] = request.exception

        if response:
            if response.get("content-type") == "application/json":
                response_string = ""
                if hasattr(response, "data"):
                    try:
                        response_string = json.dumps(
                            response.data, sort_keys=True, indent=1
                        )
                    except Exception as err:
                        response_string = str(response.content, "utf-8")
                        log_data["json_serialize_error"] = str(err)
                else:
                    response_string = str(response.content, "utf-8")
            else:
                response_string = str(response.content, "utf-8")

            log_data["response_body"] = response_string[:MAX_RESPONSE_BODY_LENGTH]

            if len(response_string) > MAX_RESPONSE_BODY_LENGTH:
                log_data["response_trimmed"] = MAX_RESPONSE_BODY_LENGTH

            log_data["response_headers"] = {**response.headers}
            log_data["status_code"] = response.status_code
            log_data["response_body"] = self.censor_sensitive_data(
                log_data["response_body"]
            )

        return log_data

    def censor_sensitive_data(self, data):
        # probably needs to be separated for the payload and the headers, but works for now

        if not data:
            return ""

        data_copy = data
        if isinstance(data, dict):
            for key in CENSOR_DATA_KEYS:
                if key in data_copy:
                    # copy only if really needed
                    if id(data) == id(data_copy):
                        data_copy = {**data}

                    data_copy[key] = "***"

        return data_copy

    def process_response(self, request, response):
        """Log data using logger."""

        # use Django logger only in the development environment.
        if request.META.get("SERVER_PORT") != os.environ.get(
            "WEB_HTTP_PORT"
        ) and request.META.get("SERVER_PORT") != os.environ.get("WEB_HTTPS_PORT"):
            log_data = self.extract_log_info(request=request, response=response)

            logger.info(msg="", extra=log_data)

        return response

    def process_exception(self, request, exception):
        """Log Exceptions."""
        request.exception = exception

        raise exception
