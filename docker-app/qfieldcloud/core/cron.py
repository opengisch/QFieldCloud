import logging
import os
from datetime import timedelta

from constance import config
from django.utils import timezone
from django_cron import CronJobBase, Schedule
from invitations.utils import get_invitation_model
from sentry_sdk import capture_message

from ..core.models import Job, Project
from ..core.utils2 import storage
from .invitations_utils import send_invitation

logger = logging.getLogger(__name__)

QGIS_CONTAINER_NAME = os.environ.get("QGIS_CONTAINER_NAME", None)

assert QGIS_CONTAINER_NAME


class DeleteExpiredInvitationsJob(CronJobBase):
    schedule = Schedule(run_every_mins=60)
    code = "qfieldcloud.delete_expired_confirmations"

    def do(self):
        Invitation = get_invitation_model()
        Invitation.objects.delete_expired_confirmations()


class ResendFailedInvitationsJob(CronJobBase):
    schedule = Schedule(run_every_mins=60)
    code = "qfieldcloud.resend_failed_invitations"

    def do(self):
        Invitation = get_invitation_model()

        invitation_emails = []
        for invitation in Invitation.objects.filter(sent__isnull=True):
            try:
                send_invitation(invitation)
                invitation_emails.append(invitation.email)
            except Exception as err:
                logger.error(err)

        logger.info(
            f'Resend {len(invitation_emails)} previously failed invitation(s) to: {", ".join(invitation_emails)}'
        )


class SetTerminatedWorkersToFinalStatusJob(CronJobBase):
    # arbitrary number 3 here, it just feel a good number since the configuration is 10 mins
    schedule = Schedule(run_every_mins=3)
    code = "qfieldcloud.set_terminated_workers_to_final_status"

    def do(self):
        jobs = Job.objects.filter(
            status__in=[Job.Status.QUEUED, Job.Status.STARTED],
            # add extra seconds just to make sure a properly finished job properly updated the status.
            started_at__lt=timezone.now()
            - timedelta(seconds=config.WORKER_TIMEOUT_S + 10),
        )

        for job in jobs:
            capture_message(
                f'Job "{job.id}" was with status "{job.status}", but worker container no longer exists. Job unexpectedly terminated.'
            )

        jobs.update(
            status=Job.Status.FAILED,
            finished_at=timezone.now(),
            feedback={
                "error_stack": "",
                "error": "Job unexpectedly terminated.",
                "error_origin": "worker_wrapper",
                "container_exit_code": -2,
            },
            output="Job unexpectedly terminated.",
        )


class DeleteObsoleteProjectPackagesJob(CronJobBase):
    schedule = Schedule(run_every_mins=60)
    code = "qfieldcloud.delete_obsolete_project_packages"

    def do(self):
        # get only the projects updated in the last a little more than an hour,
        # as we assume the rest of the projects have been cleaned from obsolete
        # packages in the previous CRON run. Also give 5 minute offset from now,
        # so there is no overlap and errors with the deletion happening from the
        # worker-wrapper.
        projects = Project.objects.filter(
            updated_at__gt=timezone.now() - timedelta(minutes=70),
            updated_at__lt=timezone.now() - timedelta(minutes=5),
        )
        job_ids = [
            str(job["id"])
            for job in Job.objects.filter(
                type=Job.Type.PACKAGE,
            )
            .exclude(
                status__in=(Job.Status.FAILED, Job.Status.FINISHED),
            )
            .values("id")
        ]

        for project in projects:
            project_id = str(project.id)
            package_ids = storage.get_stored_package_ids(project_id)

            for package_id in package_ids:
                # keep the last package
                if package_id == str(project.last_package_job_id):
                    continue

                # the job is still active, so it might be one of the new packages
                if package_id in job_ids:
                    continue

                storage.delete_stored_package(project_id, package_id)
