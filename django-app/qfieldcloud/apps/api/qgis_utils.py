import socket
import struct
import requests
import django_rq
from redis import Redis, exceptions

from rest_framework import status


def export_project(projectid, project_file):
    """Call the orchestrator API to export a project with QFieldSync"""

    queue = django_rq.get_queue('export')
    job = queue.enqueue('orchestrator.export_project',
                        projectid=projectid,
                        project_file=str(project_file))

    return job


def apply_delta(projectid, project_file, delta_file, jobid):
    """Call the orchestrator API to apply a delta file"""

    queue = django_rq.get_queue('delta')
    job = queue.enqueue('orchestrator.apply_delta',
                        job_id=jobid,
                        projectid=projectid,
                        project_file=str(project_file),
                        delta_file=delta_file)

    return job


def get_job(queue, jobid):
    """Get the job from the specified queue"""

    queue = django_rq.get_queue(queue)
    return queue.fetch_job(jobid)


def get_default_gateway():
    """Read the default gateway directly from /proc."""
    with open("/proc/net/route") as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue

            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))


def orchestrator_is_running():
    try:
        connection = Redis('redis', 6379)
        connection.set('foo', 'bar')
    except exceptions.ConnectionError:
        return False

    return True
