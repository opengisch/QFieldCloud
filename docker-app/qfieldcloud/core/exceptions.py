from rest_framework import status


class QfcError(Exception): ...


class IntegrationError(QfcError): ...


class QFieldCloudException(Exception):
    """Generic QFieldCloud Exception

    Attributes:
        code (str): error code
        message (str): error message.
        status_code (int): HTTP status code to be returned by the global Django error handler.
        log_as_error (bool): If set to `False`, the error will be logged as info level, instead of error level.
            This is useful for error that do not show problems in the system, but are server side client data assertions.
            Default is True.
    """

    code = "unknown_error"
    message = "QFieldcloud Unknown Error"
    status_code: int | None = None
    log_as_error = True

    def __init__(self, detail="", status_code=None):
        self.detail = detail

        if status_code:
            self.status_code = status_code
        elif self.status_code:
            pass
        else:
            self.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        super().__init__(self.message)

    def __str__(self):
        return self.message


class AuthenticationFailedError(QFieldCloudException):
    """Raised when QFieldCloud incoming request includes incorrect authentication."""

    code = "authentication_failed"
    message = "Authentication failed"
    status_code = status.HTTP_401_UNAUTHORIZED
    log_as_error = False


class AuthenticationViaTokenFailedError(QFieldCloudException):
    """Raised when QFieldCloud incoming request includes incorrect authentication token."""

    code = "token_authentication_failed"
    message = "Token authentication failed"
    status_code = status.HTTP_401_UNAUTHORIZED


class NotAuthenticatedError(QFieldCloudException):
    """Raised when QFieldCloud unauthenticated request fails the permission checks."""

    code = "not_authenticated"
    message = "Not authenticated"
    status_code = status.HTTP_401_UNAUTHORIZED
    log_as_error = False


class TooManyLoginAttemptsError(QFieldCloudException):
    """Raised when QFieldCloud had too many failed login attempts."""

    code = "too_many_failed_login_attempts"
    message = "Too many failed login attempts!"
    status_code = status.HTTP_401_UNAUTHORIZED


class PermissionDeniedError(QFieldCloudException):
    """Raised when the user has not the required permission for an action."""

    code = "permission_denied"
    message = "Permission denied"
    status_code = status.HTTP_403_FORBIDDEN
    log_as_error = False


class EmptyContentError(QFieldCloudException):
    """Raised when a request doesn't contain an expected content
    (e.g. a file)"""

    code = "empty_content"
    message = "Empty content"
    status_code = status.HTTP_400_BAD_REQUEST


class MultipleContentsError(QFieldCloudException):
    """Raised when a request contains multiple files
    (i.e. when it should contain at most one)"""

    code = "multiple_contents"
    message = "Multiple contents"
    status_code = status.HTTP_400_BAD_REQUEST


class ExplicitDeletionOfLastFileVersionError(QFieldCloudException):
    """Raised when the only file version is explicitly requested for deletion."""

    code = "explicit_deletion_of_last_version"
    message = "Explicit deletion of last file version is not allowed!"
    status_code = status.HTTP_400_BAD_REQUEST


class ObjectNotFoundError(QFieldCloudException):
    """Raised when a requested object doesn't exist
    (e.g. wrong project id into the request)"""

    code = "object_not_found"
    message = "Object not found"
    status_code = status.HTTP_404_NOT_FOUND
    log_as_error = False


class APIError(QFieldCloudException):
    """Raised in case of an API error"""

    code = "api_error"
    message = "API Error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


class ValidationError(QFieldCloudException):
    """Raised when validation of form data or model field fails
    (e.g. wrong field in request object)"""

    code = "validation_error"
    message = "Validation error"
    status_code = status.HTTP_400_BAD_REQUEST
    log_as_error = False


class MultipleProjectsError(QFieldCloudException):
    """Raised when the user is trying to upload more than one QGIS project
    into a QFieldCloud project"""

    code = "multiple_projects"
    message = "Multiple projects"
    status_code = status.HTTP_400_BAD_REQUEST


class RestrictedProjectModificationError(QFieldCloudException):
    """Raised when a user with insufficient role is trying to modify QGIS/QField projectfiles
    of a project that has the 'has_restricted_projectfiles' flag set"""

    code = "restricted_project_modification"
    message = "Restricted project modification"
    status_code = status.HTTP_403_FORBIDDEN


class DeltafileValidationError(QFieldCloudException):
    """Raised when a deltafile validation fails"""

    code = "invalid_deltafile"
    message = "Invalid deltafile"
    status_code = status.HTTP_400_BAD_REQUEST


class NoDeltasToApplyError(QFieldCloudException):
    """Raised when a deltafile validation fails"""

    code = "no_deltas_to_apply"
    message = "No deltas to apply"
    status_code = status.HTTP_400_BAD_REQUEST


class NoQGISProjectError(QFieldCloudException):
    """Raised when a QFieldCloud doesn't contain a QGIS project that is needed
    for the requested operation"""

    code = "no_qgis_project"
    message = "The project does not contain a valid QGIS project file"
    status_code = status.HTTP_400_BAD_REQUEST


class InvalidJobError(QFieldCloudException):
    """Raised when a requested job doesn't exist"""

    code = "invalid_job"
    message = "Invalid job"
    status_code = status.HTTP_400_BAD_REQUEST


class ProjectAlreadyExistsError(QFieldCloudException):
    """Raised when a quota limitation is hit"""

    code = "project_already_exists"
    message = "This user already owns a project with the same name."
    status_code = status.HTTP_400_BAD_REQUEST


class InvalidRangeError(QFieldCloudException):
    code = "invalid_http_range"
    message = "The provided HTTP range header is invalid."
    status_code = status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
