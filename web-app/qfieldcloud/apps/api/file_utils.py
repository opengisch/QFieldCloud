import hashlib

from django.core.files.uploadedfile import InMemoryUploadedFile


def get_sha256(file):
    """Return the sha256 hash of the file"""

    if type(file) is InMemoryUploadedFile:
        return _get_sha256_memory_file(file)
    else:
        return _get_sha256_file(file)


def _get_sha256_memory_file(file):
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()

    for chunk in file.chunks(BLOCKSIZE):
        hasher.update(chunk)

    return hasher.hexdigest()


def _get_sha256_file(file):
    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    with file as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()
