from qfieldcloud.authentication.models import AuthToken


class ClientTypeMiddleware:
    """Client type middleware.

    This middleware detects the client type based on the user agent
    and sets it on the session object.

    This client_type is required by Views later on during the QField/Sync process.

    Typically used for users connected with SSO, which don't have any `AuthToken`
    attached to the session, but future requests still need to know the client type.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "auth") and hasattr(request.auth, "client_type"):
            request.session["client_type"] = request.auth.client_type

            return self.get_response(request)

        if "client_type" not in request.session:
            user_agent = request.headers.get("user-agent", "")
            request.session["client_type"] = AuthToken.guess_client_type(user_agent)

        return self.get_response(request)
