import json
import logging
import os
import sys
import tempfile
import traceback
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import docker
import requests
from constance import config
from django.conf import settings
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from docker.client import DockerClient
from docker.errors import APIError
from docker.models.containers import Container
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    ApplyJob,
    ApplyJobDelta,
    Delta,
    Job,
    PackageJob,
    ProcessProjectfileJob,
    Secret,
)
from qfieldcloud.core.utils import get_qgis_project_file
from qfieldcloud.core.utils2 import storage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

RETRY_COUNT = 5
TIMEOUT_ERROR_EXIT_CODE = -1
DOCKER_SIGKILL_EXIT_CODE = 137
QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)

assert QGIS_CONTAINER_NAME
assert QFIELDCLOUD_HOST


class QgisException(Exception):
    pass


class JobRun:
    container_timeout_secs = config.WORKER_TIMEOUT_S
    job_class = Job
    command = []

    def __init__(self, job_id: str) -> None:
        try:
            self.job_id = job_id
            self.job = self.job_class.objects.select_related().get(id=job_id)
            self.shared_tempdir = Path(tempfile.mkdtemp(dir="/tmp"))
        except Exception as err:
            feedback: Dict[str, Any] = {}
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = str(err)
            feedback["error_origin"] = "worker_wrapper"
            feedback["error_stack"] = traceback.format_tb(tb)

            msg = "Uncaught exception when constructing a JobRun:\n"
            msg += json.dumps(msg, indent=2, sort_keys=True)

            if self.job:
                self.job.status = Job.Status.FAILED
                self.job.feedback = feedback
                self.job.save(update_fields=["status", "feedback"])
                logger.exception(msg, exc_info=err)
            else:
                logger.critical(msg, exc_info=err)

    def get_context(self) -> Dict[str, Any]:
        context = model_to_dict(self.job)

        for key, value in model_to_dict(self.job.project).items():
            context[f"project__{key}"] = value

        context["project__id"] = self.job.project.id

        return context

    def get_command(self) -> List[str]:
        return [
            p % self.get_context() for p in ["python3", "entrypoint.py", *self.command]
        ]

    def before_docker_run(self) -> None:
        pass

    def after_docker_run(self) -> None:
        pass

    def after_docker_exception(self) -> None:
        pass

    def run(self):
        feedback = {}

        try:
            self.job.status = Job.Status.STARTED
            self.job.started_at = timezone.now()
            self.job.save(update_fields=["status", "started_at"])

            self.before_docker_run()

            command = self.get_command()
            volumes = []
            volumes.append(f"{str(self.shared_tempdir)}:/io/:rw")

            exit_code, output = self._run_docker(
                command,
                volumes=volumes,
            )

            if exit_code == DOCKER_SIGKILL_EXIT_CODE:
                feedback["error"] = "Docker engine sigkill."
                feedback["error_type"] = "DOCKER_ENGINE_SIGKILL"
                feedback["error_class"] = ""
                feedback["error_origin"] = "container"
                feedback["error_stack"] = ""

                try:
                    self.job.output = output.decode("utf-8")
                    self.job.feedback = feedback
                    self.job.status = Job.Status.FAILED
                    self.job.save(update_fields=["output", "feedback"])
                    logger.info(
                        "Set job status to `failed` due to being killed by the docker engine.",
                    )
                except Exception as err:
                    logger.error(
                        "Failed to update job status, probably does not exist in the database.",
                        exc_info=err,
                    )
                # No further action required, probably received by wrapper's autoclean mechanism when the `Project` is deleted
                return
            elif exit_code == TIMEOUT_ERROR_EXIT_CODE:
                feedback["error"] = "Worker timeout error."
                feedback["error_type"] = "TIMEOUT"
                feedback["error_class"] = ""
                feedback["error_origin"] = "container"
                feedback["error_stack"] = ""
            else:
                try:
                    with open(self.shared_tempdir.joinpath("feedback.json")) as f:
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
            self.job.save(update_fields=["output", "feedback"])

            if exit_code != 0 or feedback.get("error") is not None:
                self.job.status = Job.Status.FAILED
                self.job.save(update_fields=["status"])

                try:
                    self.after_docker_exception()
                except Exception as err:
                    logger.error(
                        "Failed to run the `after_docker_exception` handler.",
                        exc_info=err,
                    )

                return

            # make sure we have reloaded the project, since someone might have changed it already
            self.job.project.refresh_from_db()

            self.after_docker_run()

            self.job.finished_at = timezone.now()
            self.job.status = Job.Status.FINISHED
            self.job.save(update_fields=["status", "finished_at"])

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
                self.job.finished_at = timezone.now()

                try:
                    self.after_docker_exception()
                except Exception as err:
                    logger.error(
                        "Failed to run the `after_docker_exception` handler.",
                        exc_info=err,
                    )

                self.job.save(update_fields=["status", "feedback", "finished_at"])
            except Exception as err:
                logger.error(
                    "Failed to handle exception and update the job status", exc_info=err
                )

    def _run_docker(
        self, command: List[str], volumes: List[str], run_opts: Dict[str, Any] = {}
    ) -> Tuple[int, bytes]:
        QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)
        QFIELDCLOUD_HOST = os.environ.get("QFIELDCLOUD_HOST", None)
        QFIELDCLOUD_WORKER_QFIELDCLOUD_URL = os.environ.get(
            "QFIELDCLOUD_WORKER_QFIELDCLOUD_URL", None
        )
        TRANSFORMATION_GRIDS_VOLUME_NAME = os.environ.get(
            "TRANSFORMATION_GRIDS_VOLUME_NAME", None
        )

        assert QGIS_CONTAINER_NAME
        assert QFIELDCLOUD_HOST
        assert QFIELDCLOUD_WORKER_QFIELDCLOUD_URL
        assert TRANSFORMATION_GRIDS_VOLUME_NAME

        token = AuthToken.objects.create(
            user=self.job.created_by,
            client_type=AuthToken.ClientType.WORKER,
            expires_at=timezone.now() + timedelta(seconds=self.container_timeout_secs),
        )

        client = docker.from_env()

        extra_envvars = {}
        pgservice_file_contents = ""
        for secret in self.job.project.secrets.all():
            if secret.type == Secret.Type.ENVVAR:
                extra_envvars[secret.name] = secret.value
            elif secret.type == Secret.Type.PGSERVICE:
                pgservice_file_contents += f"\n{secret.value}"
            else:
                raise NotImplementedError(f"Unknown secret type: {secret.type}")

        logger.info(f"Execute: {' '.join(command)}")
        volumes.append(f"{TRANSFORMATION_GRIDS_VOLUME_NAME}:/transformation_grids:ro")

        # `docker_started_at`/`docker_finished_at` tracks the time spent on docker only
        self.job.docker_started_at = timezone.now()
        self.job.save(update_fields=["docker_started_at"])

        container: Container = client.containers.run(  # type:ignore
            QGIS_CONTAINER_NAME,
            command,
            environment={
                "PGSERVICE_FILE_CONTENTS": pgservice_file_contents,
                "QFIELDCLOUD_TOKEN": token.key,
                "QFIELDCLOUD_URL": QFIELDCLOUD_WORKER_QFIELDCLOUD_URL,
                "JOB_ID": self.job_id,
                "PROJ_DOWNLOAD_DIR": "/transformation_grids",
                "QT_QPA_PLATFORM": "offscreen",
            },
            volumes=volumes,
            # TODO keep the logs somewhere or even better -> pipe them to redis and store them there
            # auto_remove=True,
            network=os.environ.get("QFIELDCLOUD_DEFAULT_NETWORK"),
            detach=True,
            mem_limit=config.WORKER_QGIS_MEMORY_LIMIT,
            cpu_shares=config.WORKER_QGIS_CPU_SHARES,
            labels={
                "app": f"{settings.ENVIRONMENT}_worker",
                "type": self.job.type,
                "job_id": str(self.job.id),
                "project_id": str(self.job.project_id),
            },
        )

        self.job.container_id = container.id
        self.job.save(update_fields=["docker_started_at", "container_id"])
        logger.info(f"Starting worker {container.id} ...")

        response = {"StatusCode": TIMEOUT_ERROR_EXIT_CODE}

        try:
            # will throw an `requests.exceptions.ConnectionError`, but the container is still alive
            response = container.wait(timeout=self.container_timeout_secs)

            if response["StatusCode"] == DOCKER_SIGKILL_EXIT_CODE:
                logger.info(
                    "Job canceled, probably due to deleted Project and Jobs.",
                )

                # No further action required, received by wrapper's autoclean mechanism when the `Project` is deleted
                return (
                    response["StatusCode"],
                    b"Job has been cancelled by parent process!",
                )

        except Exception as err:
            logger.exception("Timeout error.", exc_info=err)

        # `docker_started_at`/`docker_finished_at` tracks the time spent on docker only
        self.job.docker_finished_at = timezone.now()
        self.job.save(update_fields=["docker_finished_at"])

        logs = b""
        # Retry reading the logs, as it may fail
        # NOTE when reading the logs of a finished container, it might timeout with an ``.
        # This leads to exception and prevents the container to be removed few lines below.
        # Therefore try reading the logs, as they are important, and if it fails, just use a
        # generic "failed to read logs" message.
        # Similar issue here: https://github.com/docker/docker-py/issues/2266

        retriable = retry(
            wait=wait_random_exponential(max=10),
            stop=stop_after_attempt(RETRY_COUNT),
            retry=retry_if_exception_type(requests.exceptions.ConnectionError),
            reraise=True,
        )

        try:
            logs = retriable(lambda: container.logs())()
        except requests.exceptions.ConnectionError:
            logs = b"[QFC/Worker/1001] Failed to read logs."

        retriable(lambda: container.stop())()
        retriable(lambda: container.remove())()

        logger.info(
            f"Finished execution with code {response['StatusCode']}, logs:\n{logs.decode()}"
        )

        if response["StatusCode"] == TIMEOUT_ERROR_EXIT_CODE:
            logs += f"\nTimeout error! The job failed to finish within {self.container_timeout_secs} seconds!\n".encode()

        return response["StatusCode"], logs


class PackageJobRun(JobRun):
    job_class = PackageJob
    command = ["package", "%(project__id)s", "%(project__project_filename)s"]
    data_last_packaged_at = None

    def before_docker_run(self) -> None:
        # at the start of docker we assume we make the snapshot of the data
        self.data_last_packaged_at = timezone.now()

    def after_docker_run(self) -> None:
        # only successfully finished packaging jobs should update the Project.data_last_packaged_at
        self.job.project.data_last_packaged_at = self.data_last_packaged_at
        self.job.project.last_package_job = self.job
        self.job.project.save(
            update_fields=(
                "data_last_packaged_at",
                "last_package_job",
            )
        )

        try:
            project_id = str(self.job.project.id)
            package_ids = storage.get_stored_package_ids(project_id)
            job_ids = [
                str(job["id"])
                for job in Job.objects.filter(
                    type=Job.Type.PACKAGE,
                )
                .exclude(id=self.job.id)
                .exclude(
                    status__in=(Job.Status.FAILED, Job.Status.FINISHED),
                )
                .values("id")
            ]

            for package_id in package_ids:
                # keep the last package
                if package_id == str(self.job.project.last_package_job_id):
                    continue

                # the job is still active, so it might be one of the new packages
                if package_id in job_ids:
                    continue

                storage.delete_stored_package(project_id, package_id)
        except Exception as err:
            logger.error(
                "Failed to delete dangling packages, will be deleted via CRON later.",
                exc_info=err,
            )


class DeltaApplyJobRun(JobRun):
    job_class = ApplyJob
    command = ["delta_apply", "%(project__id)s", "%(project__project_filename)s"]

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)

        if self.job.overwrite_conflicts:
            self.command = [*self.command, "--overwrite-conflicts"]

    def _prepare_deltas(self, deltas: Iterable[Delta]):
        delta_contents = []
        delta_client_ids = []

        for delta in deltas:
            delta_contents.append(delta.content)

            if "clientId" in delta.content:
                delta_client_ids.append(delta.content["clientId"])

        local_to_remote_pk_deltas = Delta.objects.filter(
            client_id__in=delta_client_ids,
            last_modified_pk__isnull=False,
        ).values("client_id", "content__localPk", "last_modified_pk")

        client_pks_map = {}

        for delta_with_modified_pk in local_to_remote_pk_deltas:
            key = f"{delta_with_modified_pk['client_id']}__{delta_with_modified_pk['content__localPk']}"
            client_pks_map[key] = delta_with_modified_pk["last_modified_pk"]

        deltafile_contents = {
            "deltas": delta_contents,
            "files": [],
            "id": str(uuid.uuid4()),
            "project": str(self.job.project.id),
            "version": "1.0",
            "clientPks": client_pks_map,
        }

        return deltafile_contents

    @transaction.atomic()
    def before_docker_run(self) -> None:
        deltas = self.job.deltas_to_apply.all()
        deltafile_contents = self._prepare_deltas(deltas)

        self.delta_ids = [d.id for d in deltas]

        ApplyJobDelta.objects.filter(
            apply_job_id=self.job_id,
            delta_id__in=self.delta_ids,
        ).update(status=Delta.Status.STARTED)

        self.job.deltas_to_apply.update(last_status=Delta.Status.STARTED)

        with open(self.shared_tempdir.joinpath("deltafile.json"), "w") as f:
            json.dump(deltafile_contents, f)

    def after_docker_run(self) -> None:
        delta_feedback = self.job.feedback["outputs"]["apply_deltas"]["delta_feedback"]
        is_data_modified = False

        for feedback in delta_feedback:
            delta_id = feedback["delta_id"]
            status = feedback["status"]
            modified_pk = feedback["modified_pk"]

            if status == "status_applied":
                status = Delta.Status.APPLIED
                is_data_modified = True
            elif status == "status_conflict":
                status = Delta.Status.CONFLICT
            elif status == "status_apply_failed":
                status = Delta.Status.NOT_APPLIED
            else:
                status = Delta.Status.ERROR
                # not certain what happened
                is_data_modified = True

            Delta.objects.filter(pk=delta_id).update(
                last_status=status,
                last_feedback=feedback,
                last_modified_pk=modified_pk,
                last_apply_attempt_at=self.job.started_at,
                last_apply_attempt_by=self.job.created_by,
            )

            ApplyJobDelta.objects.filter(
                apply_job_id=self.job_id,
                delta_id=delta_id,
            ).update(
                status=status,
                feedback=feedback,
                modified_pk=modified_pk,
            )

        if is_data_modified:
            self.job.project.data_last_updated_at = timezone.now()
            self.job.project.save(update_fields=("data_last_updated_at",))

    def after_docker_exception(self) -> None:
        Delta.objects.filter(
            id__in=self.delta_ids,
        ).update(last_status=Delta.Status.ERROR)

        ApplyJobDelta.objects.filter(
            apply_job_id=self.job_id,
            delta_id__in=self.delta_ids,
        ).update(
            status=Delta.Status.ERROR,
        )


class ProcessProjectfileJobRun(JobRun):
    job_class = ProcessProjectfileJob
    command = [
        "process_projectfile",
        "%(project__id)s",
        "%(project__project_filename)s",
    ]

    def get_context(self, *args) -> Dict[str, Any]:
        context = super().get_context(*args)

        if not context.get("project__project_filename"):
            context["project__project_filename"] = get_qgis_project_file(
                context["project__id"]
            )

        return context

    def after_docker_run(self) -> None:
        project = self.job.project
        project.project_details = self.job.feedback["outputs"]["project_details"][
            "project_details"
        ]

        thumbnail_filename = self.shared_tempdir.joinpath("thumbnail.png")
        with open(thumbnail_filename, "rb") as f:
            thumbnail_uri = storage.upload_project_thumbail(
                project, f, "image/png", "thumbnail"
            )
        project.thumbnail_uri = project.thumbnail_uri or thumbnail_uri
        project.save(
            update_fields=(
                "project_details",
                "thumbnail_uri",
            )
        )

    def after_docker_exception(self) -> None:
        project = self.job.project

        if project.project_details is not None:
            project.project_details = None
            project.save(update_fields=("project_details",))


def cancel_orphaned_workers():
    client: DockerClient = docker.from_env()

    running_workers: List[Container] = client.containers.list(
        filters={"label": f"app={settings.ENVIRONMENT}_worker"},
    )

    if len(running_workers) == 0:
        return

    worker_ids = [c.id for c in running_workers]

    worker_with_job_ids = Job.objects.filter(container_id__in=worker_ids).values_list(
        "container_id", flat=True
    )

    # Find all running worker containers where its Project and Job were deleted from the database
    worker_without_job_ids = set(worker_ids) - set(worker_with_job_ids)

    for worker_id in worker_without_job_ids:
        container = client.containers.get(worker_id)
        try:
            container.kill()
            container.remove()
            logger.info(f"Cancel orphaned worker {worker_id}")
        except APIError:
            # Container already removed
            pass
