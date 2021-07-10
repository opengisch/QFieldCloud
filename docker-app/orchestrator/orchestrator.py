import json
import logging
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Tuple

import qfieldcloud.core.utils2.storage
from qfieldcloud.core.models import (
    ApplyJob,
    Delta,
    ExportJob,
    Job,
    ProcessQgisProjectfileJob,
    Project,
)
from qfieldcloud.core.utils2.db import use_test_db_if_exists

from .docker_utils import run_docker

logger = logging.getLogger(__name__)

TMP_DIRECTORY = os.environ.get("TMP_DIRECTORY", None)

assert TMP_DIRECTORY


class QgisException(Exception):
    pass


def export_project(job_id: str) -> Tuple[int, str]:
    """Start a QGIS docker container to export the project using libqfieldsync """

    logger.info(f"Starting a new export for project {job_id}")

    assert TMP_DIRECTORY

    with use_test_db_if_exists():
        try:
            job = ExportJob.objects.get(id=job_id)
        except ExportJob.DoesNotExist:
            logger.warning(f"ExportJob {job_id} does not exist.")
            return -1, f"ExportJob {job_id} does not exist."

        project_id = job.project_id
        project_file = job.project.project_filename
        host_tmpdir = Path(tempfile.mkdtemp(dir="/tmp"))
        qgis_tmpdir = Path(TMP_DIRECTORY).joinpath(host_tmpdir)

        job.status = Job.Status.STARTED
        job.save()

        exit_code, output = run_docker(
            f"xvfb-run python3 entrypoint.py export {project_id} {project_file}",
            volumes={qgis_tmpdir: {"bind": "/io/", "mode": "rw"}},  # type: ignore
        )

        logger.info(
            "export_project, projectid: {}, project_file: {}, exit_code: {}, output:\n\n{}".format(
                project_id, project_file, exit_code, output.decode("utf-8")
            )
        )

        feedback = {}
        try:
            with open(host_tmpdir.joinpath("feedback.json"), "r") as f:
                feedback = json.load(f)

                if feedback.get("error"):
                    feedback["error_origin"] = "container"
        except Exception as err:
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = err
            feedback["error_origin"] = "orchestrator"
            feedback["error_stack"] = traceback.format_tb(tb)

        feedback["container_exit_code"] = exit_code

        job.output = output.decode("utf-8")
        job.feedback = feedback

        if exit_code != 0 or feedback.get("error") is not None:
            job.status = Job.Status.FAILED
            job.save()
            raise QgisException(output)

        job.status = Job.Status.FINISHED
        job.save()

        return exit_code, output.decode("utf-8")


def apply_deltas(job_id, project_file):
    """Start a QGIS docker container to apply a deltafile using the
    apply-delta script"""

    logger.info(f"Starting a new delta apply job {job_id}")

    with use_test_db_if_exists():
        try:
            job = ApplyJob.objects.get(id=job_id)
        except ApplyJob.DoesNotExist:
            logger.warning(f"ApplyJob {job_id} does not exist.")
            return -1, f"ApplyJob {job_id} does not exist."

        project_id = job.project_id
        overwrite_conflicts = job.overwrite_conflicts
        orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
        qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)

        deltas = job.deltas_to_apply.all()
        deltas.update(last_status=Delta.Status.STARTED)

        # prepare client id pks
        delta_contents = []
        delta_client_ids = []
        for delta in deltas:
            delta_contents.append(delta.content)

            if "clientId" in delta.content:
                delta_client_ids.append(delta.content["clientId"])

        local_to_remote_pk_deltas = Delta.objects.filter(
            content__clientId__in=delta_client_ids,
            last_modified_pk__isnull=False,
        ).values("content__clientId", "content__localPk", "last_modified_pk")

        client_pks_map = {}

        for delta in local_to_remote_pk_deltas:
            key = f"{delta['content__clientId']}__{delta['content__localPk']}"
            client_pks_map[key] = delta["last_modified_pk"]

        json_content = {
            "deltas": delta_contents,
            "files": [],
            "id": str(uuid.uuid4()),
            "project": str(project_id),
            "version": "1.0",
            "clientPks": client_pks_map,
        }

        with open(qgis_tempdir.joinpath("deltafile.json"), "w") as f:
            json.dump(json_content, f)

        overwrite_conflicts_arg = "--overwrite-conflicts" if overwrite_conflicts else ""
        exit_code, output = run_docker(
            f"xvfb-run python3 entrypoint.py apply-delta {project_id} {project_file} {overwrite_conflicts_arg}",
            volumes={qgis_tempdir: {"bind": "/io/", "mode": "rw"}},
        )

        logger.info(
            f"""
===============================================================================
| Apply deltas finished
===============================================================================
Project ID: {project_id}
Project file: {project_file}
Exit code: {exit_code}
Output:
------------------------------------------------------------------------------S
{output.decode('utf-8')}
------------------------------------------------------------------------------E
"""
        )

        deltalog_file = os.path.join(orchestrator_tempdir, "deltalog.json")
        with open(deltalog_file, "r") as f:
            deltalog = json.load(f)

            for feedback in deltalog:
                delta_id = feedback["delta_id"]
                status = feedback["status"]
                modified_pk = feedback["modified_pk"]

                if status == "status_applied":
                    status = Delta.Status.APPLIED
                elif status == "status_conflict":
                    status = Delta.Status.CONFLICT
                elif status == "status_apply_failed":
                    status = Delta.Status.NOT_APPLIED
                else:
                    status = Delta.Status.ERROR

                Delta.objects.filter(pk=delta_id).update(
                    last_status=status,
                    last_feedback=feedback,
                    last_modified_pk=modified_pk,
                )

        job.status = Job.Status.FINISHED
        job.output = output.decode("utf-8")
        job.save()

        return exit_code, output.decode("utf-8")


def process_projectfile(job_id):
    logger.info(f"Starting a new process QGIS projectfile job {job_id}")

    with use_test_db_if_exists():
        try:
            job = ProcessQgisProjectfileJob.objects.get(id=job_id)
        except ProcessQgisProjectfileJob.DoesNotExist:
            logger.warning(f"ProcessQgisProjectfileJob {job_id} does not exist.")
            return -1, f"ProcessQgisProjectfileJob {job_id} does not exist."

        orchestrator_tempdir = tempfile.mkdtemp(dir="/tmp")
        qgis_tempdir = Path(TMP_DIRECTORY).joinpath(orchestrator_tempdir)

        project = job.project

        job.status = Job.Status.STARTED
        job.save()
        project.status = Project.Status.PROCESS_PROJECTFILE
        project.save()

        exit_code, output = run_docker(
            f"xvfb-run python3 entrypoint.py process-qgis-projectfile {project.id} {project.project_filename}",
            volumes={qgis_tempdir: {"bind": "/io/", "mode": "rw"}},
        )

        logger.info(
            "postprocess QGIS projectfile, projectid: {}, project_file: {}, exit_code: {}, output:\n\n{}".format(
                project.id, project.project_filename, exit_code, output.decode("utf-8")
            )
        )

        if not exit_code == 0:
            job.status = Job.Status.FAILED
            job.output = output.decode("utf-8")
            job.save()
            raise QgisException(output)

        thumbnail_filename = Path(orchestrator_tempdir).joinpath("thumbnail.png")
        with open(thumbnail_filename, "rb") as f:
            thumbnail_uri = qfieldcloud.core.utils2.storage.upload_project_thumbail(
                job.project, f, "image/png", "thumbnail"
            )

        feedback_filename = Path(orchestrator_tempdir).joinpath("feedback.json")
        try:
            with open(feedback_filename, "r") as f:
                feedback = json.load(f)
        except FileNotFoundError:
            feedback = "Feedback log not available"

        logger.info("Project processed successfully")

        job.status = Job.Status.STARTED
        job.output = output.decode("utf-8")
        job.feedback = feedback
        job.save()
        project.status = Project.Status.IDLE
        project.thumbnail_uri = project.thumbnail_uri or thumbnail_uri
        project.save()

        return exit_code, output.decode("utf-8"), feedback


def check_status():
    """Launch a container to check that everything is working
    correctly."""

    exit_code, output = run_docker('echo "QGIS container is running"')

    logger.info(
        "check_status, exit_code: {}, output:\n\n{}".format(
            exit_code, output.decode("utf-8")
        )
    )

    if not exit_code == 0:
        raise QgisException(output)
    return exit_code, output.decode("utf-8")
