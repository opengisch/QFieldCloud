from email.message import Message
from typing import cast


def get_file_name_from_header(content_disposition: str) -> str | None:
    """Extracts the file name from the `Content-Disposition` header."""
    message = Message()
    message["Content-Disposition"] = content_disposition
    file_name = cast(str | None, message.get_filename())

    return file_name
