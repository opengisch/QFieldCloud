import json
import logging
import shutil
import sys
import tempfile
import traceback
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import docker
import requests
import sentry_sdk
from constance import config
from django.conf import settings
from django.core.files.base import ContentFile
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
from qfieldcloud.core.utils2 import packages, storage
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
TMP_FILE = Path("/tmp")


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
            self.shared_tempdir = Path(tempfile.mkdtemp(dir=TMP_FILE))
        except Exception as err:
            feedback: dict[str, Any] = {}
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

        self.debug_qgis_container_is_enabled = (
            settings.DEBUG and settings.DEBUG_QGIS_DEBUGPY_PORT
        )

        if self.debug_qgis_container_is_enabled:
            logger.warning(
                f"Debugging is enabled for job {self.job.id}. The worker will wait for debugger to attach on port {settings.DEBUG_QGIS_DEBUGPY_PORT}."
            )

    def get_context(self) -> dict[str, Any]:
        context = model_to_dict(self.job)

        for key, value in model_to_dict(self.job.project).items():
            context[f"project__{key}"] = value

        context["project__id"] = self.job.project.id

        return context

    def get_command(self) -> list[str]:
        context = self.get_context()

        if self.debug_qgis_container_is_enabled:
            debug_flags = [
                "-m",
                "debugpy",
                "--listen",
                f"0.0.0.0:{settings.DEBUG_QGIS_DEBUGPY_PORT}",
                "--wait-for-client",
            ]
        else:
            debug_flags = []

        return [
            p % context
            for p in ["python3", *debug_flags, "entrypoint.py", *self.command]
        ]

    def before_docker_run(self) -> None:
        pass

    def after_docker_run(self) -> None:
        pass

    def after_docker_exception(self) -> None:
        pass

    def run(self):
        """The main and first method to be called on `JobRun`.

        Should not be overloaded by inheriting classes,
        they should use `before_docker_run`, `after_docker_run`
        and `after_docker_exception` hooks.
        """
        feedback = {}

        try:
            self.job.status = Job.Status.STARTED
            self.job.started_at = timezone.now()
            self.job.save(update_fields=["status", "started_at"])

            # # # CONCURRENCY CHECK # # #
            # safety check whether there are no concurrent jobs running for that particular project
            # if there are, reset the job back to `PENDING`
            concurrent_jobs_count = (
                self.job.project.jobs.filter(
                    status__in=[Job.Status.QUEUED, Job.Status.STARTED],
                )
                .exclude(pk=self.job.pk)
                .count()
            )

            if concurrent_jobs_count > 0:
                self.job.status = Job.Status.PENDING
                self.job.started_at = None
                self.job.save(update_fields=["status", "started_at"])
                logger.warning(f"Concurrent jobs occured for job {self.job}.")
                sentry_sdk.capture_message(
                    f"Concurrent jobs occured for job {self.job}."
                )
                return
            # # # /CONCURRENCY CHECK # # #

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
                    self.job.refresh_from_db()
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

            shutil.rmtree(str(self.shared_tempdir), ignore_errors=True)

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
        self, command: list[str], volumes: list[str], run_opts: dict[str, Any] = {}
    ) -> tuple[int, bytes]:
        assert settings.QFIELDCLOUD_WORKER_QFIELDCLOUD_URL
        assert settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME

        token = AuthToken.objects.create(
            user=self.job.created_by,
            client_type=AuthToken.ClientType.WORKER,
            expires_at=timezone.now() + timedelta(seconds=self.container_timeout_secs),
        )

        client = docker.from_env()

        extra_envvars = {}
        pgservice_file_contents = ""
        for secret in Secret.objects.for_user_and_project(
            self.job.triggered_by, self.job.project
        ):
            if secret.type == Secret.Type.ENVVAR:
                extra_envvars[secret.name] = secret.value
            elif secret.type == Secret.Type.PGSERVICE:
                pgservice_file_contents += f"\n{secret.value}"
            else:
                raise NotImplementedError(f"Unknown secret type: {secret.type}")

        logger.info(f"Execute: {' '.join(command)}")
        volumes.append(
            f"{settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME}:/transformation_grids:ro"
        )

        # used for local development of QFieldCloud
        if settings.DEBUG_QGIS_LIBQFIELDSYNC_HOST_PATH:
            volumes.append(
                f"{settings.DEBUG_QGIS_LIBQFIELDSYNC_HOST_PATH}:/libqfieldsync:ro"
            )

        # used for local development of QFieldCloud
        if settings.DEBUG_QGIS_QFIELDCLOUD_SDK_HOST_PATH:
            volumes.append(
                f"{settings.DEBUG_QGIS_QFIELDCLOUD_SDK_HOST_PATH}:/qfieldcloud-sdk-python:ro"
            )

        # `docker_started_at`/`docker_finished_at` tracks the time spent on docker only
        self.job.docker_started_at = timezone.now()
        self.job.save(update_fields=["docker_started_at"])

        environment = {
            **extra_envvars,
            "PGSERVICE_FILE_CONTENTS": pgservice_file_contents,
            "QFIELDCLOUD_EXTRA_ENVVARS": json.dumps(sorted(extra_envvars.keys())),
            "QFIELDCLOUD_TOKEN": token.key,
            "QFIELDCLOUD_URL": settings.QFIELDCLOUD_WORKER_QFIELDCLOUD_URL,
            "JOB_ID": self.job_id,
            "PROJ_DOWNLOAD_DIR": "/transformation_grids",
            "QT_QPA_PLATFORM": "offscreen",
        }
        ports = {}

        if self.debug_qgis_container_is_enabled:
            # NOTE the `qgis` container must expose the same port as the one used by `debugpy`,
            # otherwise the vscode deubgger won't be able to connect
            # NOTE the port must be passed here and not in the `docker-compose` file,
            # because the `qgis` container is started with docker in docker and the `docker-compose`
            # configuration is valid only for the brief moment when the stack is built and started,
            # but not when new `qgis` containers are started dynamically by the worker wrapper
            ports.update(
                {
                    f"{settings.DEBUG_QGIS_DEBUGPY_PORT}/tcp": settings.DEBUG_QGIS_DEBUGPY_PORT,
                }
            )

        container: Container = client.containers.run(  # type:ignore
            settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
            command,
            environment=environment,
            ports=ports,
            volumes=volumes,
            # TODO stream the logs to something like redis, so they can be streamed back in project jobs page to the user live
            # auto_remove=True,
            network=settings.QFIELDCLOUD_DEFAULT_NETWORK,
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
    command = [
        "package",
        "%(project__id)s",
        "%(project__the_qgis_file_name)s",
        "%(project__packaging_offliner)s",
    ]
    data_last_packaged_at = None

    def before_docker_run(self) -> None:
        # at the start of docker we assume we make the snapshot of the data
        self.data_last_packaged_at = timezone.now()

    def after_docker_run(self) -> None:
        # only successfully finished packaging jobs should update the Project.data_last_packaged_at
        self.job.project.data_last_packaged_at = self.data_last_packaged_at
        self.job.project.save(update_fields=("data_last_packaged_at",))

        packages.delete_obsolete_packages(projects=[self.job.project])


class DeltaApplyJobRun(JobRun):
    job_class = ApplyJob
    command = ["delta_apply", "%(project__id)s", "%(project__the_qgis_file_name)s"]

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)

        if self.job.overwrite_conflicts:
            self.command = [*self.command, "--overwrite-conflicts"]

    def _prepare_deltas(self, deltas: Iterable[Delta]) -> dict[str, Any]:
        delta_contents = []
        delta_client_ids = []

        for delta in deltas:
            delta_contents.append(delta.content)

            if "clientId" in delta.content:
                delta_client_ids.append(delta.content["clientId"])

        local_to_remote_pk_deltas = Delta.objects.filter(
            client_id__in=delta_client_ids,
            last_modified_pk__isnull=False,
        ).values(
            "client_id", "content__localLayerId", "content__localPk", "last_modified_pk"
        )

        client_pks_map = {}

        for delta_with_modified_pk in local_to_remote_pk_deltas:
            key = f"{delta_with_modified_pk['client_id']}__{delta_with_modified_pk['content__localLayerId']}__{delta_with_modified_pk['content__localPk']}"
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
        ).update(
            last_status=Delta.Status.ERROR,
            last_feedback=None,
            last_modified_pk=None,
            last_apply_attempt_at=self.job.started_at,
            last_apply_attempt_by=self.job.created_by,
        )

        ApplyJobDelta.objects.filter(
            apply_job_id=self.job_id,
            delta_id__in=self.delta_ids,
        ).update(
            status=Delta.Status.ERROR,
            feedback=None,
            modified_pk=None,
        )


class ProcessProjectfileJobRun(JobRun):
    job_class = ProcessProjectfileJob
    command = [
        "process_projectfile",
        "%(project__id)s",
        "%(project__the_qgis_file_name)s",
    ]

    def get_context(self, *args) -> dict[str, Any]:
        context = super().get_context(*args)

        if not context.get("project__the_qgis_file_name"):
            context["project__the_qgis_file_name"] = get_qgis_project_file(
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
            # TODO Delete with QF-4963 Drop support for legacy storage
            if project.uses_legacy_storage:
                legacy_thumbnail_uri = storage.upload_project_thumbail(
                    project, f, "image/png", "thumbnail"
                )
                project.legacy_thumbnail_uri = (
                    project.legacy_thumbnail_uri or legacy_thumbnail_uri
                )
            else:
                project.thumbnail = ContentFile(f.read(), "dummy_thumbnail_name.png")

        project.save(
            update_fields=(
                "project_details",
                "legacy_thumbnail_uri",
                "thumbnail",
            )
        )

        # for non-legacy storage, keep only one thumbnail version if so.
        if not project.uses_legacy_storage and project.thumbnail:
            storage.purge_previous_thumbnails_versions(project)

    def after_docker_exception(self) -> None:
        project = self.job.project

        if project.project_details is not None:
            project.project_details = None
            project.save(update_fields=("project_details",))


def cancel_orphaned_workers() -> None:
    client: DockerClient = docker.from_env()

    try:
        running_workers: list[Container] = client.containers.list(
            filters={"label": f"app={settings.ENVIRONMENT}_worker"},
        )
    except docker.errors.NotFound:
        # We don't mind empty references since they mean there is no
        # orphan to cancel.
        return

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
