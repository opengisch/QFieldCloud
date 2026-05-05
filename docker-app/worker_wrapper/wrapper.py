import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import requests
import sentry_sdk
import yaml
from constance import config
from django.conf import settings
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

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
from qfieldcloud.core.utils2 import packages
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

# TODO @suricactus: Delete when QF-6868 Log DEBUG level when DEBUG=True, see https://app.clickup.com/t/QF-6868
if settings.DEBUG:
    logger.setLevel(logging.DEBUG)

RETRY_COUNT = 5
TIMEOUT_ERROR_EXIT_CODE = -1
KUBERNETES_SIGKILL_EXIT_CODE = 137
TRANSFORMATION_GRIDS_PATH = "/transformation_grids"
"""Path inside the worker container where the transformation grids volume `settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME` is mounted."""

TOKEN_EXPIRATION_TIME_BUFFER_S = 60
"""Extra time in seconds for the dedicated worker token to keep the token valid, in addition to `JobRun.container_timeout_secs`. Useful when the worker takes longer to start."""

# Kubernetes configuration
K8S_JOB_NAMESPACE = getattr(settings, "KUBERNETES_JOB_NAMESPACE", "default")
K8S_SHARED_VOLUME_CLAIM = getattr(settings, "KUBERNETES_SHARED_VOLUME_CLAIM", "qfieldcloud-shared-pvc")
K8S_SHARED_VOLUME_MOUNT_PATH = getattr(settings, "KUBERNETES_SHARED_VOLUME_MOUNT_PATH", "/shared")
K8S_JOB_TTL_SECONDS = getattr(settings, "KUBERNETES_JOB_TTL_SECONDS", 3600)
K8S_JOB_BACKOFF_LIMIT = getattr(settings, "KUBERNETES_JOB_BACKOFF_LIMIT", 0)


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
            # Use shared volume path instead of local temp directory
            self.shared_tempdir = Path(K8S_SHARED_VOLUME_MOUNT_PATH) / f"job-{job_id}"
            self.shared_tempdir.mkdir(parents=True, exist_ok=True)
            
            # Initialize Kubernetes client
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            
            self.batch_v1 = client.BatchV1Api()
            self.core_v1 = client.CoreV1Api()
            
        except Exception as err:
            feedback: dict[str, Any] = {}
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = str(err)
            feedback["error_origin"] = "worker_wrapper"
            feedback["error_stack"] = traceback.format_tb(tb)

            msg = "Uncaught exception when constructing a JobRun:\n"
            msg += json.dumps(msg, indent=2, sort_keys=True)

            if hasattr(self, 'job') and self.job:
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

    def get_volumes(self) -> list:
        """Return Kubernetes volume mounts for the Job"""
        volumes = []
        volume_mounts = []
        
        # Shared volume for job data exchange
        volumes.append(client.V1Volume(
            name="shared-data",
            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                claim_name=K8S_SHARED_VOLUME_CLAIM
            )
        ))
        volume_mounts.append(client.V1VolumeMount(
            name="shared-data",
            mount_path=K8S_SHARED_VOLUME_MOUNT_PATH
        ))
        
        # Transformation grids volume (read-only)
        volumes.append(client.V1Volume(
            name="transformation-grids",
            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                claim_name=settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME
            )
        ))
        volume_mounts.append(client.V1VolumeMount(
            name="transformation-grids",
            mount_path=TRANSFORMATION_GRIDS_PATH,
            read_only=True
        ))
        
        # Custom CA volume if exists
        if Path(settings.QFIELDCLOUD_CUSTOM_CA_FILENAME).exists():
            volumes.append(client.V1Volume(
                name="custom-ca",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=settings.QFIELDCLOUD_CUSTOM_CA_VOLUME_NAME
                )
            ))
            volume_mounts.append(client.V1VolumeMount(
                name="custom-ca",
                mount_path=settings.QFIELDCLOUD_CUSTOM_CA_DIR,
                read_only=True
            ))
        
        return volumes, volume_mounts

    def get_environment(self) -> dict[str, str]:
        extra_envvars = {}

        if Path(settings.QFIELDCLOUD_CUSTOM_CA_FILENAME).exists():
            extra_envvars["REQUESTS_CA_BUNDLE"] = (
                settings.QFIELDCLOUD_CUSTOM_CA_FILENAME
            )

        pgservice_file_contents = ""
        for secret in Secret.objects.for_user_and_project(  # type:ignore
            self.job.triggered_by, self.job.project
        ):
            if secret.type == Secret.Type.ENVVAR:
                extra_envvars[secret.name] = secret.value
            elif secret.type == Secret.Type.PGSERVICE:
                pgservice_file_contents += f"\n{secret.value}"
            else:
                raise NotImplementedError(f"Unknown secret type: {secret.type}")

        # expire the token a bit after the container timeout to avoid edge cases
        token_expires_at = timezone.now() + timedelta(
            seconds=self.container_timeout_secs + TOKEN_EXPIRATION_TIME_BUFFER_S
        )
        token = AuthToken.objects.create(
            user=self.job.created_by,
            client_type=AuthToken.ClientType.WORKER,
            expires_at=token_expires_at,
        )

        environment = {
            **extra_envvars,
            "PGSERVICE_FILE_CONTENTS": pgservice_file_contents,
            "QFIELDCLOUD_EXTRA_ENVVARS": json.dumps(sorted(extra_envvars.keys())),
            "QFIELDCLOUD_TOKEN": token.key,
            "QFIELDCLOUD_URL": settings.QFIELDCLOUD_WORKER_QFIELDCLOUD_URL,
            "JOB_ID": self.job_id,
            "PROJ_DOWNLOAD_DIR": TRANSFORMATION_GRIDS_PATH,
            "QT_QPA_PLATFORM": "offscreen",
        }

        return environment

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

            exit_code, output = self._run_kubernetes_job(command)

            if exit_code == KUBERNETES_SIGKILL_EXIT_CODE:
                feedback["error"] = "Kubernetes sigkill."
                feedback["error_type"] = "KUBERNETES_SIGKILL"
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
                    feedback_file = self.shared_tempdir.joinpath("feedback.json")
                    if feedback_file.exists():
                        with open(feedback_file) as f:
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

            # Clean up shared directory
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

    def _run_kubernetes_job(self, command: list[str]) -> tuple[int, bytes]:
        """Create and run a Kubernetes Job instead of a Docker container"""
        assert settings.QFIELDCLOUD_WORKER_QFIELDCLOUD_URL
        assert settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME

        job_name = f"qfc-job-{self.job_id[:8]}-{uuid.uuid4().hex[:6]}"
        
        volumes, volume_mounts = self.get_volumes()
        environment = self.get_environment()
        
        # Convert environment dict to K8s format
        env_vars = []
        for key, value in environment.items():
            env_vars.append(client.V1EnvVar(name=key, value=value))
        
        # Resource limits
        resources = client.V1ResourceRequirements(
            limits={
                "memory": f"{config.WORKER_QGIS_MEMORY_LIMIT}",
                "cpu": f"{config.WORKER_QGIS_CPU_SHARES}m" if config.WORKER_QGIS_CPU_SHARES else None
            },
            requests={
                "memory": f"{config.WORKER_QGIS_MEMORY_LIMIT}",
                "cpu": f"{config.WORKER_QGIS_CPU_SHARES}m" if config.WORKER_QGIS_CPU_SHARES else "100m"
            }
        )
        
        # Container definition
        container = client.V1Container(
            name="qgis-worker",
            image=settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
            command=["python3"] if not command[0].startswith("python3") else None,
            args=command if command[0].startswith("python3") else command,
            env=env_vars,
            volume_mounts=volume_mounts,
            resources=resources,
        )
        
        # Add debug port if enabled
        if self.debug_qgis_container_is_enabled:
            container.ports = [
                client.V1ContainerPort(
                    container_port=settings.DEBUG_QGIS_DEBUGPY_PORT,
                    name="debugpy"
                )
            ]
        
        # Pod template
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": f"{settings.ENVIRONMENT}_worker",
                    "type": self.job.type,
                    "job_id": str(self.job.id),
                    "project_id": str(self.job.project_id),
                }
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                volumes=volumes,
                containers=[container],
            )
        )
        
        # Job definition
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=K8S_JOB_NAMESPACE,
                labels={
                    "app": f"{settings.ENVIRONMENT}_worker",
                    "type": self.job.type,
                    "job_id": str(self.job.id),
                    "project_id": str(self.job.project_id),
                }
            ),
            spec=client.V1JobSpec(
                parallelism=1,
                completions=1,
                backoff_limit=K8S_JOB_BACKOFF_LIMIT,
                ttl_seconds_after_finished=K8S_JOB_TTL_SECONDS,
                active_deadline_seconds=self.container_timeout_secs,
                template=pod_template,
            )
        )
        
        logger.info(f"Creating Kubernetes Job: {job_name} with command: {' '.join(command)}")
        
        # Store job name in database
        self.job.container_id = job_name  # Reusing container_id field for job name
        self.job.docker_started_at = timezone.now()
        self.job.save(update_fields=["docker_started_at", "container_id"])
        
        try:
            # Create the Job
            self.batch_v1.create_namespaced_job(
                namespace=K8S_JOB_NAMESPACE,
                body=job
            )
            
            # Wait for Job completion
            exit_code, logs = self._wait_for_job_completion(job_name)
            
            return exit_code, logs
            
        except ApiException as e:
            logger.error(f"Kubernetes API exception: {e}")
            return TIMEOUT_ERROR_EXIT_CODE, f"Kubernetes API error: {e}".encode()
        finally:
            # Clean up the Job
            self._delete_job(job_name)
    
    def _wait_for_job_completion(self, job_name: str) -> tuple[int, bytes]:
        """Wait for Kubernetes Job to complete and return exit code and logs"""
        poll_interval = 2  # seconds
        start_time = time.time()
        timeout_seconds = self.container_timeout_secs + 30  # Add buffer
        
        job_completed = False
        exit_code = TIMEOUT_ERROR_EXIT_CODE
        logs = b""
        
        while not job_completed and (time.time() - start_time) < timeout_seconds:
            try:
                job = self.batch_v1.read_namespaced_job_status(
                    name=job_name,
                    namespace=K8S_JOB_NAMESPACE
                )
                
                if job.status.succeeded is not None and job.status.succeeded > 0:
                    logger.info(f"Job {job_name} succeeded")
                    job_completed = True
                    exit_code = 0
                    
                elif job.status.failed is not None and job.status.failed > 0:
                    logger.info(f"Job {job_name} failed")
                    job_completed = True
                    exit_code = 1
                    
                elif job.status.active is not None and job.status.active > 0:
                    # Job still running
                    pass
                    
                else:
                    # Unknown status
                    logger.warning(f"Job {job_name} has unknown status: {job.status}")
                    
            except ApiException as e:
                if e.status == 404:
                    logger.error(f"Job {job_name} not found")
                    break
                else:
                    logger.warning(f"Error reading job status: {e}")
            
            if not job_completed:
                time.sleep(poll_interval)
        
        # Get logs from the pod
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=K8S_JOB_NAMESPACE,
                label_selector=f"job-name={job_name}"
            )
            
            if pods.items:
                # Get logs from the first pod
                pod_name = pods.items[0].metadata.name
                logs = self.core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=K8S_JOB_NAMESPACE
                ).encode('utf-8')
                
        except ApiException as e:
            logger.warning(f"Failed to get logs for job {job_name}: {e}")
            logs = b"[QFC/Worker] Failed to retrieve job logs"
        
        self.job.docker_finished_at = timezone.now()
        self.job.save(update_fields=["docker_finished_at"])
        
        if exit_code == TIMEOUT_ERROR_EXIT_CODE:
            logs += f"\nTimeout error! The job failed to finish within {self.container_timeout_secs} seconds!\n".encode()
        
        return exit_code, logs
    
    def _delete_job(self, job_name: str) -> None:
        """Delete Kubernetes Job and its pods"""
        try:
            # Delete the job
            self.batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=K8S_JOB_NAMESPACE,
                propagation_policy="Background"
            )
            logger.info(f"Deleted Kubernetes Job: {job_name}")
            
            # Delete associated pods (they should be deleted automatically with propagation_policy="Background")
            # but we'll explicitly delete them to ensure cleanup
            try:
                pods = self.core_v1.list_namespaced_pod(
                    namespace=K8S_JOB_NAMESPACE,
                    label_selector=f"job-name={job_name}"
                )
                for pod in pods.items:
                    self.core_v1.delete_namespaced_pod(
                        name=pod.metadata.name,
                        namespace=K8S_JOB_NAMESPACE
                    )
            except ApiException:
                pass  # Pods might already be deleted
                
        except ApiException as e:
            logger.warning(f"Failed to delete job {job_name}: {e}")


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


class ApplyDeltaJobRun(JobRun):
    job_class = ApplyJob
    command = ["apply_deltas", "%(project__id)s", "%(project__the_qgis_file_name)s"]

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

        assert context.get("project__the_qgis_file_name")

        return context

    def after_docker_run(self) -> None:
        project = self.job.project
        project.project_details = self.job.feedback["outputs"]["project_details"][
            "project_details"
        ]

        project.save(update_fields=("project_details",))

    def after_docker_exception(self) -> None:
        project = self.job.project

        if project.project_details is not None:
            project.project_details = None
            project.save(update_fields=("project_details",))


class CreateProjectJobRun(JobRun):
    job_class = Job
    command = [
        "create_project",
        "%(project__id)s",
    ]


def cancel_orphaned_workers() -> None:
    """Cancel orphaned Kubernetes Jobs that don't have corresponding database entries"""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    
    batch_v1 = client.BatchV1Api()
    
    try:
        # List all worker jobs
        jobs = batch_v1.list_namespaced_job(
            namespace=K8S_JOB_NAMESPACE,
            label_selector=f"app={settings.ENVIRONMENT}_worker"
        )
    except ApiException as e:
        logger.error(f"Failed to list Kubernetes Jobs: {e}")
        return
    
    if not jobs.items:
        return
    
    # Get all running job names from database
    job_names = [job.metadata.name for job in jobs.items]
    active_jobs = Job.objects.filter(container_id__in=job_names).values_list("container_id", flat=True)
    
    # Find orphaned jobs
    orphaned_job_names = set(job_names) - set(active_jobs)
    
    for job_name in orphaned_job_names:
        try:
            batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=K8S_JOB_NAMESPACE,
                propagation_policy="Background"
            )
            logger.info(f"Cancel orphaned Kubernetes Job: {job_name}")
        except ApiException as e:
            if e.status != 404:  # Don't log if already deleted
                logger.warning(f"Failed to delete orphaned job {job_name}: {e}")
