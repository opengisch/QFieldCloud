from deprecated import deprecated
from rest_framework import status


class QfcError(Exception):
    ...


class IntegrationError(QfcError):
    ...


class QFieldCloudException(Exception):
    """Generic QFieldCloud Exception"""

    code = "unknown_error"
    message = "QFieldcloud Unknown Error"
    status_code = None

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


class StatusNotOkError(QFieldCloudException):
    """Raised when some parts of QFieldCloud are not working as expected"""

    code = "status_not_ok"
    message = "Status not ok"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class AuthenticationFailedError(QFieldCloudException):
    """Raised when QFieldCloud incoming request includes incorrect authentication."""

    code = "authentication_failed"
    message = "Authentication failed"
    status_code = status.HTTP_401_UNAUTHORIZED


class NotAuthenticatedError(QFieldCloudException):
    """Raised when QFieldCloud unauthenticated request fails the permission checks."""

    code = "not_authenticated"
    message = "Not authenticated"
    status_code = status.HTTP_401_UNAUTHORIZED


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


class EmptyContentError(QFieldCloudException):
    """Raised when a request doesn't contain an expected content
    (e.g. a file)"""

    code = "empty_content"
    message = "Empty content"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class MultipleContentsError(QFieldCloudException):
    """Raised when a request contains multiple files
    (i.e. when it should contain at most one)"""

    code = "multiple_contents"
    message = "Multiple contents"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class ObjectNotFoundError(QFieldCloudException):
    """Raised when a requested object doesn't exist
    (e.g. wrong project id into the request)"""

    code = "object_not_found"
    message = "Object not found"
    status_code = status.HTTP_400_BAD_REQUEST


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


class MultipleProjectsError(QFieldCloudException):
    """Raised when the user is trying to upload more than one QGIS project
    into a QFieldCloud project"""

    code = "multiple_projects"
    message = "Multiple projects"
    status_code = status.HTTP_400_BAD_REQUEST


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


class QGISPackageError(QFieldCloudException):
    """Raised when the QGIS package of a project fails"""

    code = "qgis_package_error"
    message = "QGIS package failed"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    if "Unable to open file with QGIS" in message:
        message = "QGIS is unable to open the QGIS project"


class ProjectAlreadyExistsError(QFieldCloudException):
    """Raised when a quota limitation is hit"""

    code = "project_already_exists"
    message = "This user already owns a project with the same name."
    status_code = status.HTTP_400_BAD_REQUEST


@deprecated("moved to subscription")
class ReachedMaxOrganizationMembersError(QFieldCloudException):
    """Raised when an organization has exhausted its quota of members"""

    code = "organization_has_max_number_of_members"
    message = "Cannot add new organization members, account limit has been reached."
    status_code = status.HTTP_403_FORBIDDEN
