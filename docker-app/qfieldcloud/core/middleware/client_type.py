from typing import Callable

from django.http import HttpRequest, HttpResponse

from qfieldcloud.authentication.models import AuthToken


class ClientTypeMiddleware:
    """Client type middleware.

    This middleware detects the client type based on the user agent
    and sets it on the session object.

    This client_type is required by Views later on during the QField/Sync process.

    Typically used for users connected with SSO, which don't have any `AuthToken`
    attached to the session, but future requests still need to know the client type.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Sets the client type in the session.
        This client type will be required later for the QField/Sync requests process.
        """
        if getattr(request, "auth", None) and hasattr(request.auth, "client_type"):  # type: ignore[attr-defined]
            client_type = request.auth.client_type  # type: ignore[attr-defined]
        else:
            user_agent = request.headers.get("user-agent", "")
            guessed_client_type = AuthToken.guess_client_type(user_agent)

            client_type = request.session.get("client_type", guessed_client_type)

        if request.session.get("client_type") != client_type:
            request.session["client_type"] = client_type

        return self.get_response(request)
