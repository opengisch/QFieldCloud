import logging

from axes.signals import user_locked_out
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.translation import gettext as _
from rest_framework.exceptions import PermissionDenied

from .models import Job, Project

logger = logging.getLogger(__name__)


@receiver(user_locked_out)
def raise_permission_denied(*args, **kwargs):
    raise PermissionDenied(_("Too many failed login attempts"))


# Register signals
@receiver(pre_save, sender=Job)
def update_job_project_status(sender, instance, **kwargs):
    # TODO integrate with project.status property
    # TODO optimize use 'updated_fields'
    project = instance.project
    if project.static_status == Project.Status.DELETED:
        return

    project_status = Project.Status.OK
    if instance.status in [Job.Status.QUEUED or Job.Status.STARTED]:
        project_status = Project.Status.BUSY
    elif not project.project_filename:
        project_status = Project.Status.FAILED
    project.static_status = project_status
    project.save()
