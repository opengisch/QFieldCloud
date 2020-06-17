import socket
import struct
import requests

from rest_framework import status


def export_project(project_directory, project_file):
    """Call the orchestrator API to export a project with QFieldSync"""

    url = ''.join([
        'http://',
        get_default_gateway(),
        ':5000/export-project',
        '?project-dir=',
        project_directory,
        '&project-file=',
        str(project_file),
    ])

    return requests.get(url)


def apply_delta(project_directory, project_file, delta_file):
    """Call the orchestrator API to apply a delta file"""

    url = ''.join([
        'http://',
        get_default_gateway(),
        ':5000/apply-delta',
        '?project-dir=',
        project_directory,
        '&project-file=',
        str(project_file),
        '&delta-file=',
        delta_file,
    ])

    return requests.get(url)


def get_default_gateway():
    """Read the default gateway directly from /proc."""
    with open("/proc/net/route") as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue

            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))


def orchestrator_is_running():
    ORCHESTRATOR_URL = 'http://' + get_default_gateway() + ':5000/'

    try:
        response = requests.get(ORCHESTRATOR_URL)
    except requests.exceptions.ConnectionError:
        return False

    if status.is_success(response.status_code):
        return True
    return False
