import re

VERSION_SUFFIX_REGEX = re.compile(r"v20[0-9]{12}-[a-f0-9]{8}$")
"""A regex to ensure the format of the version suffix is correct."""
