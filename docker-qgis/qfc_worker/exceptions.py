def humanize_error(exc: BaseException) -> str:
    """Extracts the messages from an exception and its causes, and joins them in a single string.

    Will result in like:
    ```
    Main error message
      - Caused by: First cause message
      - Caused by: Second cause message
    ```
    """

    prev_exc: BaseException | None = exc
    parts = []

    while prev_exc:
        parts.append(str(prev_exc))
        prev_exc = prev_exc.__cause__

    return "\n  - Caused by: ".join(parts)


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


class UnableToContinueException(QfcWorkerException):
    message = "Unable to continue workflow:\n%(reason)s"


class WorkflowModificationException(Exception): ...


class WorkflowValidationException(Exception): ...
