import qfieldcloud.core.models


def get_attachment_dir_prefix(
    project: qfieldcloud.core.models.Project, filename: str
) -> str:  # noqa: F821
    """Returns the attachment dir where the file belongs to or empty string if it does not.

    Args:
        project: project to check
        filename: filename to check

    Returns:
        the attachment dir or empty string if no match found
    """
    for attachment_dir in project.attachment_dirs:
        if filename.startswith(attachment_dir):
            return attachment_dir

    return ""
