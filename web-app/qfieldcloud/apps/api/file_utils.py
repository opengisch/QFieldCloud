import hashlib


def get_sha256(file):
    """Return the sha256 hash of the file"""

    BLOCKSIZE = 65536
    hasher = hashlib.sha256()
    with file as f:
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
    return hasher.hexdigest()
