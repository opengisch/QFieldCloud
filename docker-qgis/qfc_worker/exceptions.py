class QfcWorkerException(Exception):
    """QFieldCloud Exception"""

    message = ""

    def __init__(self, message: str | None = None, **kwargs):
        self.message = (message or self.message) % kwargs
        self.details = kwargs

        super().__init__(self.message)


class ProjectFileNotFoundException(QfcWorkerException):
    message = 'Project file "%(the_qgis_file_name)s" does not exist'


class InvalidFileExtensionException(QfcWorkerException):
    message = 'Project file "%(the_qgis_file_name)s" has unknown file extension "%(extension)s"'


class InvalidXmlFileException(QfcWorkerException):
    message = "Project file is an invalid XML document:\n%(xml_error)s"


class FailedThumbnailGenerationException(QfcWorkerException):
    message = "Failed to generate project thumbnail:\n%(reason)s"


class WorkflowValidationException(Exception): ...
