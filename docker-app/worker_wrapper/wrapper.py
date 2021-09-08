import json
import logging
import os
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import docker
import qfieldcloud.core.utils2.storage
import requests
from django.db import transaction
from django.forms.models import model_to_dict
from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    ExportJob,
    Job,
    ProcessProjectfileJob,
)

logger = logging.getLogger(__name__)

TMP_DIRECTORY = os.environ.get("TMP_DIRECTORY", None)
QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)

assert TMP_DIRECTORY
assert QGIS_CONTAINER_NAME
assert QFIELDCLOUD_HOST


class QgisException(Exception):
    pass


class JobRun:
    container_timeout_secs = 3 * 60
    job_class = Job
    command = ""

    def __init__(self, job_id: str) -> None:
        try:
            assert TMP_DIRECTORY

            self.job_id = job_id
            self.job = self.job_class.objects.select_related().get(id=job_id)
            self.host_tempdir = Path(tempfile.mkdtemp(dir="/tmp"))
            self.qgis_tempdir = Path(TMP_DIRECTORY).joinpath(self.host_tempdir)
        except Exception as err:
            feedback = {}
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = str(err)
            feedback["error_origin"] = "worker_wrapper"
            feedback["error_stack"] = traceback.format_tb(tb)

            msg = "Uncaught exception when constructing a JobRun:\n"
            msg += json.dumps(msg, indent=2, sort_keys=True)

            if self.job:
                self.job.status = Job.Status.FAILED
                self.job.feedback = feedback
                self.job.save()
                logger.exception(msg, exc_info=err)
            else:
                logger.critical(msg, exc_info=err)

    def get_context(self) -> Dict[str, Any]:
        context = model_to_dict(self.job)

        for key, value in model_to_dict(self.job.project).items():
            context[f"project__{key}"] = value

        context["project__id"] = self.job.project.id

        return context

    def get_command(self) -> str:
        # command = f"xvfb-run -e /dev/stdout -w 1 python3 entrypoint.py {self.command}"
        command = f"python3 entrypoint.py {self.command}"
        return command % self.get_context()

    def before_docker(self) -> None:
        pass

    def after_docker(self) -> None:
        pass

    def run(self):
        feedback = {}

        try:
            self.job.status = Job.Status.STARTED
            self.job.save()

            self.before_docker()

            command = self.get_command()
            volumes = {}
            volumes[str(self.qgis_tempdir)] = {"bind": "/io/", "mode": "rw"}

            exit_code, output = self._run_docker(
                command,
                volumes=volumes,
            )

            try:
                with open(self.host_tempdir.joinpath("feedback.json"), "r") as f:
                    feedback = json.load(f)

                    if feedback.get("error"):
                        feedback["error_origin"] = "container"
            except Exception as err:
                if not isinstance(feedback, dict):
                    feedback = {"error_feedback": feedback}

                (_type, _value, tb) = sys.exc_info()
                feedback["error"] = str(err)
                feedback["error_origin"] = "worker_wrapper"
                feedback["error_stack"] = traceback.format_tb(tb)

            feedback["container_exit_code"] = exit_code

            self.job.output = output.decode("utf-8")
            self.job.feedback = feedback

            if exit_code != 0 or feedback.get("error") is not None:
                self.job.status = Job.Status.FAILED
                self.job.save()
                return

            self.job.status = Job.Status.FINISHED
            self.job.save()

            self.after_docker()

        except Exception as err:
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = str(err)
            feedback["error_origin"] = "worker_wrapper"
            feedback["error_stack"] = traceback.format_tb(tb)

            if isinstance(err, requests.exceptions.ReadTimeout):
                feedback["error_timeout"] = True

            logger.error(
                f"Failed job run:\n{json.dumps(feedback, sort_keys=True)}", exc_info=err
            )

            try:
                self.job.status = Job.Status.FAILED
                self.job.feedback = feedback
                self.job.save()
            except Exception as err:
                logger.error("Failed to handle exception and update the job status")
                logger.exception(err, exc_info=err)

    def _run_docker(
        self, command: str, volumes: Dict[str, str], run_opts: Dict[str, Any] = {}
    ) -> Tuple[int, bytes]:
        QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
        QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)

        assert QGIS_CONTAINER_NAME
        assert QFIELDCLOUD_HOST

        client = docker.from_env()

        logger.info(f"Execute: {command}")

        container = client.containers.run(
            QGIS_CONTAINER_NAME,
            command,
            environment={
                "STORAGE_ACCESS_KEY_ID": os.environ.get("STORAGE_ACCESS_KEY_ID"),
                "STORAGE_SECRET_ACCESS_KEY": os.environ.get(
                    "STORAGE_SECRET_ACCESS_KEY"
                ),
                "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
                "STORAGE_REGION_NAME": os.environ.get("STORAGE_REGION_NAME"),
                "STORAGE_ENDPOINT_URL": os.environ.get("STORAGE_ENDPOINT_URL"),
                "QT_QPA_PLATFORM": "offscreen",
            },
            volumes=volumes,
            # TODO keep the logs somewhere or even better -> pipe them to redis and store them there
            # auto_remove=True,
            network=os.environ.get("QFIELDCLOUD_DEFAULT_NETWORK"),
            detach=True,
        )

        response = {"StatusCode": -1}

        try:
            response = container.wait(timeout=self.container_timeout_secs)
        except Exception as err:
            logger.exception("Timeout error.", exc_info=err)

        logs = container.logs()
        container.stop()
        container.remove()
        logger.info(
            f"Finished execution with code {response['StatusCode']}, logs:\n{logs}"
        )

        return response["StatusCode"], logs


class ExportJobRun(JobRun):
    job_class = ExportJob
    command = "export %(project__id)s %(project__project_filename)s"


class DeltaApplyJobRun(JobRun):
    job_class = ApplyJob
    command = "delta_apply %(project__id)s %(project__project_filename)s"

    def get_command(self) -> str:
        command = super().get_command()
        command += " --overwrite-conflicts" if self.job.overwrite_conflicts else ""

        return command

    def _prepare_deltas(self, deltas: Iterable[Delta]):
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

        deltafile_contents = {
            "deltas": delta_contents,
            "files": [],
            "id": str(uuid.uuid4()),
            "project": str(self.job.project.id),
            "version": "1.0",
            "clientPks": client_pks_map,
        }

        return deltafile_contents

    def before_docker(self) -> None:
        with transaction.atomic():
            deltas = Delta.objects.select_for_update().filter(
                last_status=Delta.Status.PENDING
            )

            self.job.deltas_to_apply.add(*deltas)

            ApplyJobDelta.objects.filter(
                apply_job_id=self.job_id,
                delta_id__in=[d.id for d in deltas],
            ).update(status=Delta.Status.STARTED)

            deltafile_contents = self._prepare_deltas(deltas)

            deltas.update(last_status=Delta.Status.STARTED)

            with open(self.qgis_tempdir.joinpath("deltafile.json"), "w") as f:
                json.dump(deltafile_contents, f)

    def after_docker(self) -> None:
        delta_feedback = self.job.feedback["steps"][1]["outputs"]["delta_feedback"]

        for feedback in delta_feedback:
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

            ApplyJobDelta.objects.filter(
                apply_job_id=self.job_id,
                delta_id=delta_id,
            ).update(
                status=status,
                feedback=feedback,
                modified_pk=modified_pk,
            )


class ProcessProjectfileJobRun(JobRun):
    job_class = ProcessProjectfileJob
    command = "process_projectfile %(project__id)s %(project__project_filename)s"

    def after_docker(self) -> None:
        thumbnail_filename = self.host_tempdir.joinpath("thumbnail.png")
        project = self.job.project

        with open(thumbnail_filename, "rb") as f:
            thumbnail_uri = qfieldcloud.core.utils2.storage.upload_project_thumbail(
                project, f, "image/png", "thumbnail"
            )
        project.thumbnail_uri = project.thumbnail_uri or thumbnail_uri
        project.save()
