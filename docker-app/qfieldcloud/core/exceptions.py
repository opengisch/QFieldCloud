from rest_framework import status


class QFieldCloudException(Exception):
    """Generic QFieldCloud Exception"""

    def __init__(
            self,
            code='unknown_error',
            message='QFieldcloud Unknown Error',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR):

        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

    def __str__(self):
        return self.message


class StatusNotOkError(QFieldCloudException):
    """Raised when some parts of QFieldCloud are not working as expected"""

    def __init__(self, message='Status not ok'):
        self.code = 'status_not_ok'
        self.message = message
        self.status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class EmptyContentError(QFieldCloudException):
    """Raised when a request doesn't contain an expected content
    (e.g. a file)"""

    def __init__(self, message='Empty content'):
        self.code = 'empty_content'
        self.message = message
        self.status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class ObjectNotFoundError(QFieldCloudException):
    """Raised when a requested object doesn't exist
    (e.g. wrong project id into the request)"""

    def __init__(self, message='Object not found'):
        self.code = 'object_not_found'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class APIError(QFieldCloudException):
    """Raised in case of an API error"""

    def __init__(
            self,
            message='API Error',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.code = 'api_error'
        self.message = message
        self.status_code = status_code


class ValidationError(QFieldCloudException):
    """Raised when validation of form data or model field fails
    (e.g. wrong field in request object)"""

    def __init__(self, message='Validation Error'):
        self.code = 'validation_error'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class MultipleProjectsError(QFieldCloudException):
    """Raised when the user is trying to upload more than one QGIS project
    into a QFieldCloud project"""

    def __init__(self, message='Multiple Projects'):
        self.code = 'multiple_projects'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class DeltafileValidationError(QFieldCloudException):
    """Raised when a deltafile validation fails"""

    def __init__(self, message='Invalid delta file'):
        self.code = 'invalid_deltafile'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class NoQGISProjectError(QFieldCloudException):
    """Raised when a QFieldCloud doesn't contain a QGIS project that is needed
    for the requested operation"""

    def __init__(
            self,
            message='The project does not contain a valid QGIS project file'):
        self.code = 'no_qgis_project'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class InvalidJobError(QFieldCloudException):
    """Raised when a requested job doesn't exist"""

    def __init__(self, message='Invalid job'):
        self.code = 'invalid_job'
        self.message = message
        self.status_code = status.HTTP_400_BAD_REQUEST


class QGISExportError(QFieldCloudException):
    """Raised when the QGIS export of a project fails"""

    def __init__(self, message='QGIS export failed'):
        self.code = 'qgis_export_error'
        self.message = message
        self.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        if 'Unable to open file with QGIS' in self.message:
            self.message = 'QGIS is unable to open the QGIS project'
