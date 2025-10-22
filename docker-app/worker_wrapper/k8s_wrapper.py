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
import time

import requests
import sentry_sdk
from constance import config
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
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
K8S_SIGKILL_EXIT_CODE = 137
TMP_FILE = Path("/tmp")


class QgisException(Exception):
    pass


class K8sJobRun:
    container_timeout_secs = config.WORKER_TIMEOUT_S
    job_class = Job
    command = []

    def __init__(self, job_id: str) -> None:
        try:
            self.job_id = job_id
            self.job = self.job_class.objects.select_related().get(id=job_id)
            self.shared_tempdir = Path(tempfile.mkdtemp(dir=TMP_FILE))

            # Initialize Kubernetes client
            try:
                # Try in-cluster config first (when running inside k8s)
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                # Fall back to local kubeconfig (for development)
                k8s_config.load_kube_config()

            self.k8s_core_v1 = client.CoreV1Api()
            self.k8s_batch_v1 = client.BatchV1Api()

            # K8s namespace for jobs
            self.namespace = getattr(settings, "QFIELDCLOUD_K8S_NAMESPACE", "default")

            # Job name for k8s (must be DNS compliant)
            self.k8s_job_name = f"qfc-worker-{self.job_id}".lower().replace("_", "-")

        except Exception as err:
            feedback: dict[str, Any] = {}
            (_type, _value, tb) = sys.exc_info()
            feedback["error"] = str(err)
            feedback["error_origin"] = "worker_wrapper"
            feedback["error_stack"] = traceback.format_tb(tb)

            msg = "Uncaught exception when constructing a K8sJobRun:\n"
            msg += json.dumps(feedback, indent=2, sort_keys=True)

            if hasattr(self, "job") and self.job:
                self.job.status = Job.Status.FAILED
                self.job.feedback = feedback
                self.job.save(update_fields=["status", "feedback"])
                logger.exception(msg, exc_info=err)
            else:
                logger.critical(msg, exc_info=err)

        self.debug_qgis_container_is_enabled = settings.DEBUG and getattr(
            settings, "DEBUG_QGIS_DEBUGPY_PORT", None
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

    def get_volume_mounts(self) -> list[client.V1VolumeMount]:
        volume_mounts = [
            client.V1VolumeMount(name="shared-io", mount_path="/io", read_only=False),
        ]

        # Add transformation grids volume if configured
        if getattr(settings, "QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME", None):
            volume_mounts.append(
                client.V1VolumeMount(
                    name="transformation-grids",
                    mount_path="/transformation_grids",
                    read_only=True,
                )
            )

        return volume_mounts

    def get_volumes(self) -> list[client.V1Volume]:
        volumes = [
            client.V1Volume(
                name="shared-io",
                host_path=client.V1HostPathVolumeSource(
                    path=str(self.shared_tempdir), type="Directory"
                ),
            )
        ]

        # Add transformation grids volume if configured
        if getattr(settings, "QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME", None):
            # For K8s, this could be a PVC, ConfigMap, or HostPath
            # Using PVC as the most common case
            volumes.append(
                client.V1Volume(
                    name="transformation-grids",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=settings.QFIELDCLOUD_TRANSFORMATION_GRIDS_VOLUME_NAME
                    ),
                )
            )

        return volumes

    def get_environment_vars(self) -> list[client.V1EnvVar]:
        env_vars = []
        extra_envvars = {}

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

        token = AuthToken.objects.create(
            user=self.job.created_by,
            client_type=AuthToken.ClientType.WORKER,
            expires_at=timezone.now() + timedelta(seconds=self.container_timeout_secs),
        )

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

        for key, value in environment.items():
            env_vars.append(client.V1EnvVar(name=key, value=str(value)))

        return env_vars

    def before_k8s_run(self) -> None:
        """Hook called before starting the Kubernetes job"""
        pass

    def after_k8s_run(self) -> None:
        """Hook called after successful Kubernetes job completion"""
        pass

    def after_k8s_exception(self) -> None:
        """Hook called after Kubernetes job failure"""
        pass

    def run(self):
        """The main and first method to be called on `K8sJobRun`.

        Should not be overloaded by inheriting classes,
        they should use `before_k8s_run`, `after_k8s_run`
        and `after_k8s_exception` hooks.
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
                logger.warning(f"Concurrent jobs occurred for job {self.job}.")
                sentry_sdk.capture_message(
                    f"Concurrent jobs occurred for job {self.job}."
                )
                return
            # # # /CONCURRENCY CHECK # # #

            self.before_k8s_run()

            command = self.get_command()

            exit_code, output = self._run_k8s_job(command)

            if exit_code == K8S_SIGKILL_EXIT_CODE:
                feedback["error"] = "Kubernetes job sigkill."
                feedback["error_type"] = "K8S_JOB_SIGKILL"
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

            self.job.output = (
                output.decode("utf-8") if isinstance(output, bytes) else output
            )
            self.job.feedback = feedback
            self.job.save(update_fields=["output", "feedback"])

            if exit_code != 0 or feedback.get("error") is not None:
                self.job.status = Job.Status.FAILED
                self.job.save(update_fields=["status"])

                try:
                    self.after_k8s_exception()
                except Exception as err:
                    logger.error(
                        "Failed to run the `after_k8s_exception` handler.",
                        exc_info=err,
                    )

                return

            # make sure we have reloaded the project, since someone might have changed it already
            self.job.project.refresh_from_db()

            self.after_k8s_run()

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
                    self.after_k8s_exception()
                except Exception as err:
                    logger.error(
                        "Failed to run the `after_k8s_exception` handler.",
                        exc_info=err,
                    )

                self.job.save(update_fields=["status", "feedback", "finished_at"])
            except Exception as err:
                logger.error(
                    "Failed to handle exception and update the job status", exc_info=err
                )

    def _run_k8s_job(self, command: list[str]) -> tuple[int, str]:
        """Run a Kubernetes Job and wait for completion"""
        assert settings.QFIELDCLOUD_WORKER_QFIELDCLOUD_URL

        volume_mounts = self.get_volume_mounts()
        volumes = self.get_volumes()
        env_vars = self.get_environment_vars()

        # Create resource limits and requests
        resources = client.V1ResourceRequirements(
            limits={
                "memory": config.WORKER_QGIS_MEMORY_LIMIT,
                "cpu": str(
                    config.WORKER_QGIS_CPU_SHARES / 1024.0
                ),  # Convert from shares to CPU units
            },
            requests={
                "memory": config.WORKER_QGIS_MEMORY_LIMIT,
                "cpu": str(
                    config.WORKER_QGIS_CPU_SHARES / 1024.0 / 2
                ),  # Request half of limit
            },
        )

        # Create container spec
        container = client.V1Container(
            name="qgis-worker",
            image=settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
            command=command,
            env=env_vars,
            volume_mounts=volume_mounts,
            resources=resources,
        )

        # Add debug port if enabled
        if self.debug_qgis_container_is_enabled:
            container.ports = [
                client.V1ContainerPort(
                    container_port=int(settings.DEBUG_QGIS_DEBUGPY_PORT), protocol="TCP"
                )
            ]

        # Create pod template
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": f"{getattr(settings, 'ENVIRONMENT', 'dev')}-worker",
                    "type": self.job.type,
                    "job-id": str(self.job.id),
                    "project-id": str(self.job.project_id),
                }
            ),
            spec=client.V1PodSpec(
                containers=[container],
                volumes=volumes,
                restart_policy="Never",
                # Use service account with appropriate permissions
                service_account_name=getattr(
                    settings, "QFIELDCLOUD_K8S_SERVICE_ACCOUNT", "default"
                ),
            ),
        )

        # Create job spec
        job_spec = client.V1JobSpec(
            template=pod_template,
            backoff_limit=0,  # Don't retry failed jobs
            active_deadline_seconds=self.container_timeout_secs,
        )

        # Create job object
        k8s_job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=self.k8s_job_name,
                namespace=self.namespace,
                labels={
                    "app": f"{getattr(settings, 'ENVIRONMENT', 'dev')}-worker",
                    "managed-by": "qfieldcloud-worker-wrapper",
                },
            ),
            spec=job_spec,
        )

        logger.info(f"Execute K8s Job {self.k8s_job_name}: {' '.join(command)}")

        # Start timing
        self.job.docker_started_at = (
            timezone.now()
        )  # Keep same field name for compatibility
        self.job.save(update_fields=["docker_started_at"])

        try:
            # Create the job
            self.k8s_batch_v1.create_namespaced_job(
                namespace=self.namespace, body=k8s_job
            )

            # Store job name for tracking
            self.job.container_id = (
                self.k8s_job_name
            )  # Keep same field name for compatibility
            self.job.save(update_fields=["container_id"])

            logger.info(f"Starting K8s worker job {self.k8s_job_name}...")

            # Wait for job completion
            exit_code, logs = self._wait_for_job_completion()

            return exit_code, logs

        except ApiException as e:
            logger.error(f"Failed to create K8s job: {e}")
            return TIMEOUT_ERROR_EXIT_CODE, f"Failed to create K8s job: {e}"
        finally:
            # End timing
            self.job.docker_finished_at = (
                timezone.now()
            )  # Keep same field name for compatibility
            self.job.save(update_fields=["docker_finished_at"])

    def _wait_for_job_completion(self) -> tuple[int, str]:
        """Wait for the Kubernetes job to complete and retrieve logs"""
        start_time = time.time()

        while time.time() - start_time < self.container_timeout_secs:
            try:
                # Check job status
                job_status = self.k8s_batch_v1.read_namespaced_job_status(
                    name=self.k8s_job_name, namespace=self.namespace
                )

                if job_status.status.completion_time:
                    # Job completed successfully
                    logs = self._get_job_logs()
                    self._cleanup_job()
                    return 0, logs
                elif job_status.status.failed:
                    # Job failed
                    logs = self._get_job_logs()
                    self._cleanup_job()
                    return 1, logs

                # Job still running, wait a bit
                time.sleep(5)

            except ApiException as e:
                logger.error(f"Error checking job status: {e}")
                time.sleep(5)

        # Timeout reached
        logs = self._get_job_logs()
        self._cleanup_job()
        timeout_msg = f"\nTimeout error! The job failed to finish within {self.container_timeout_secs} seconds!\n"
        return TIMEOUT_ERROR_EXIT_CODE, logs + timeout_msg

    def _get_job_logs(self) -> str:
        """Retrieve logs from the job's pod"""
        try:
            # Get pods for this job
            pods = self.k8s_core_v1.list_namespaced_pod(
                namespace=self.namespace, label_selector=f"job-name={self.k8s_job_name}"
            )

            if not pods.items:
                return "[QFC/Worker/K8s/1001] No pods found for job."

            # Get logs from the first pod
            pod_name = pods.items[0].metadata.name
            logs = self.k8s_core_v1.read_namespaced_pod_log(
                name=pod_name, namespace=self.namespace, container="qgis-worker"
            )

            return logs

        except ApiException as e:
            logger.error(f"Failed to retrieve logs: {e}")
            return f"[QFC/Worker/K8s/1002] Failed to read logs: {e}"

    def _cleanup_job(self) -> None:
        """Clean up the Kubernetes job and its pods"""
        try:
            # Delete the job (this will also delete associated pods)
            self.k8s_batch_v1.delete_namespaced_job(
                name=self.k8s_job_name,
                namespace=self.namespace,
                propagation_policy="Background",
            )
            logger.info(f"Cleaned up K8s job {self.k8s_job_name}")
        except ApiException as e:
            logger.warning(f"Failed to cleanup job {self.k8s_job_name}: {e}")


# Inherit from K8sJobRun for all job types
class K8sPackageJobRun(K8sJobRun):
    job_class = PackageJob
    command = [
        "package",
        "%(project__id)s",
        "%(project__the_qgis_file_name)s",
        "%(project__packaging_offliner)s",
    ]
    data_last_packaged_at = None

    def before_k8s_run(self) -> None:
        # at the start of k8s job we assume we make the snapshot of the data
        self.data_last_packaged_at = timezone.now()

    def after_k8s_run(self) -> None:
        # only successfully finished packaging jobs should update the Project.data_last_packaged_at
        self.job.project.data_last_packaged_at = self.data_last_packaged_at
        self.job.project.save(update_fields=("data_last_packaged_at",))

        packages.delete_obsolete_packages(projects=[self.job.project])


class K8sApplyDeltaJobRun(K8sJobRun):
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
    def before_k8s_run(self) -> None:
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

    def after_k8s_run(self) -> None:
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

    def after_k8s_exception(self) -> None:
        if hasattr(self, "delta_ids"):
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


class K8sProcessProjectfileJobRun(K8sJobRun):
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

    def after_k8s_run(self) -> None:
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

    def after_k8s_exception(self) -> None:
        project = self.job.project

        if project.project_details is not None:
            project.project_details = None
            project.save(update_fields=("project_details",))


def cancel_orphaned_k8s_workers() -> None:
    """Cancel orphaned Kubernetes worker jobs"""
    try:
        # Initialize Kubernetes client
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()

        k8s_batch_v1 = client.BatchV1Api()
        namespace = getattr(settings, "QFIELDCLOUD_K8S_NAMESPACE", "default")
        environment = getattr(settings, "ENVIRONMENT", "dev")

        # List all jobs with our label
        jobs = k8s_batch_v1.list_namespaced_job(
            namespace=namespace,
            label_selector=f"app={environment}-worker,managed-by=qfieldcloud-worker-wrapper",
        )

        if len(jobs.items) == 0:
            return

        job_names = [job.metadata.name for job in jobs.items]

        # Find jobs that exist in k8s but not in database
        # Extract job IDs from k8s job names (format: qfc-worker-{job_id})
        k8s_job_ids = []
        for name in job_names:
            if name.startswith("qfc-worker-"):
                job_id = name.replace("qfc-worker-", "").replace("-", "_")
                k8s_job_ids.append(job_id)

        # Check which jobs exist in database
        existing_job_ids = set(
            Job.objects.filter(id__in=k8s_job_ids).values_list("id", flat=True)
        )

        # Find orphaned jobs
        orphaned_job_ids = set(k8s_job_ids) - existing_job_ids
        orphaned_job_names = [
            f"qfc-worker-{job_id.replace('_', '-')}" for job_id in orphaned_job_ids
        ]

        # Delete orphaned jobs
        for job_name in orphaned_job_names:
            try:
                k8s_batch_v1.delete_namespaced_job(
                    name=job_name, namespace=namespace, propagation_policy="Background"
                )
                logger.info(f"Cancelled orphaned K8s worker job {job_name}")
            except ApiException as e:
                logger.warning(f"Failed to cancel orphaned job {job_name}: {e}")

    except Exception as e:
        logger.error(f"Error cancelling orphaned K8s workers: {e}")


# Compatibility aliases - use these instead of the original Docker-based classes
JobRun = K8sJobRun
PackageJobRun = K8sPackageJobRun
ApplyDeltaJobRun = K8sApplyDeltaJobRun
ProcessProjectfileJobRun = K8sProcessProjectfileJobRun
cancel_orphaned_workers = cancel_orphaned_k8s_workers
