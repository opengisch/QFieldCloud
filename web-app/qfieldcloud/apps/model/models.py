import os
import shutil
import uuid

from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.dispatch import receiver

from qfieldcloud.apps.api import file_utils


def reserved_words_validator(value):
    reserved_words = ['user', 'users', 'project', 'projects', 'owner', 'push',
                      'file', 'files', 'collaborator', 'collaborators',
                      'member', 'organization', 'qfield', 'qfieldcloud',
                      'history', 'version']
    if value.lower() in reserved_words:
        raise ValidationError('"{}" is a reserved word!'.format(value))


# http://springmeblog.com/2018/how-to-implement-multiple-user-types-with-django/

class User(AbstractUser):
    TYPE_USER = 1
    TYPE_ORGANIZATION = 2

    TYPE_CHOICES = (
        (TYPE_USER, 'user'),
        (TYPE_ORGANIZATION, 'organization'),
    )

    user_type = models.PositiveSmallIntegerField(
        choices=TYPE_CHOICES, default=TYPE_USER)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta.get_field('username').validators.append(
            reserved_words_validator)

    def __str__(self):
        return self.username


class Organization(User):
    # TODO: add extra specific organization fields, like website url etc

    organization_owner = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='owner',
        limit_choices_to=models.Q(user_type=User.TYPE_USER))

    # TODO: add a post_save to set automatically the user_type

    class Meta:
        verbose_name = 'organization'
        verbose_name_plural = 'organizations'


class OrganizationMember(models.Model):
    ROLE_ADMIN = 1
    ROLE_MEMBER = 2

    ROLE_CHOICES = (
        (ROLE_ADMIN, 'admin'),
        (ROLE_MEMBER, 'member'),
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        limit_choices_to=models.Q(user_type=User.TYPE_ORGANIZATION),
        related_name='members')
    member = models.ForeignKey(
        User, on_delete=models.CASCADE,
        limit_choices_to=models.Q(user_type=User.TYPE_USER))
    role = models.PositiveSmallIntegerField(
        choices=ROLE_CHOICES, default=ROLE_MEMBER)

    def __str__(self):
        return self.organization.username + ': ' + self.member.username


class Project(models.Model):
    """Represent a QFieldcloud project.
    It corresponds to a directory on the file system.

    The owner of a project is an Organization.
    """

    allowed_symbols_validator = RegexValidator(
        r'^[-a-zA-Z0-9_]*$',
        'Only letters, numbers, underscores or hyphens are allowed.')

    min_lenght_validator = RegexValidator(
        r'^.{3,}$',
        'The project name must be at least 3 characters long.')

    first_sybol_validator = RegexValidator(
        r'^[a-zA-Z].*$',
        'The project name must begin with a letter.')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        validators=[allowed_symbols_validator,
                    min_lenght_validator,
                    first_sybol_validator,
                    reserved_words_validator],
        help_text='Project name'
    )

    description = models.TextField(blank=True)
    private = models.BooleanField(default=False)
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name + ' (' + str(self.id) + ')'

    def export_to_filesystem(self):

        export_dir = os.path.join(
            settings.PROJECTS_ROOT,
            str(self.id),
            'real_files')

        shutil.rmtree(export_dir, ignore_errors=True)
        os.makedirs(export_dir, exist_ok=True)

        files = File.objects.filter(project=self)
        for f in files:
            src = os.path.join(
                settings.PROJECTS_ROOT,
                f.get_last_file_version().stored_file.name)
            dest = os.path.join(
                export_dir,
                f.original_path)

            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
        return export_dir

    def get_qgis_project_file(self):
        """Return the QGIS project file of the project"""

        try:
            project_file_obj = File.objects.get(
                models.Q(project=self),
                models.Q(original_path__iendswith='.qgs') | models.Q(original_path__iendswith='.qgz'))
            return project_file_obj
        except File.DoesNotExist:
            return None

    def delete(self):
        # Delete the project's directory too
        shutil.rmtree(
            os.path.join(
                settings.PROJECTS_ROOT,
                str(self.id)),
            ignore_errors=True)
        return super().delete()


class ProjectCollaborator(models.Model):
    ROLE_ADMIN = 1
    ROLE_MANAGER = 2
    ROLE_EDITOR = 3
    ROLE_REPORTER = 4
    ROLE_READER = 5

    ROLE_CHOICES = (
        (ROLE_ADMIN, 'admin'),
        (ROLE_MANAGER, 'manager'),
        (ROLE_EDITOR, 'editor'),
        (ROLE_REPORTER, 'reporter'),
        (ROLE_READER, 'reader'),
    )

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='collaborators',
    )
    collaborator = models.ForeignKey(
        User, on_delete=models.CASCADE,
        limit_choices_to=models.Q(type=User.TYPE_USER))
    role = models.PositiveSmallIntegerField(
        choices=ROLE_CHOICES, default=ROLE_READER)

    def __str__(self):
        return self.project.name + ': ' + self.collaborator.username


class FileManager(models.Manager):

    def delete(self):
        for obj in self.get_queryset():
            obj.delete()


class File(models.Model):
    """This represent the original file as seen by the client"""

    def file_path(instance, filename):
        return os.path.join(str(instance.project.id), filename)

    project = models.ForeignKey(Project, on_delete=models.CASCADE)

    # absolute_path of the file, filename included
    original_path = models.CharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.original_path

    def get_last_file_version(self):
        return FileVersion.objects.filter(file=self).latest('created_at')

    def get_version(self, version):
        try:
            return FileVersion.objects.get(file=self, created_at=version)
        except FileVersion.DoesNotExist:
            return None

    def size(self):
        return self.get_last_file_version().stored_file.size

    def sha256(self):
        return self.get_last_file_version().sha256()

    def name(self):
        return self.original_path

    def versions(self):
        return FileVersion.objects.filter(file=self)


class FileVersion(models.Model):

    def file_path(instance, filename):
        return os.path.join(
            str(instance.file.project.id),
            'versions',
            str(uuid.uuid4()))

    file = models.ForeignKey(File, on_delete=models.CASCADE)

    stored_file = models.FileField(upload_to=file_path)
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True)

    def sha256(self):
        return file_utils.get_sha256(self.stored_file.file)

    def size(self):
        return self.stored_file.size

    def __str__(self):
        return self.stored_file.name + ' ' + str(self.created_at)


class DeltaFile(models.Model):

    STATUS_PENDING = 1  # delta file has been received, but have not started application
    STATUS_BUSY = 2  # currently being applied
    STATUS_APPLIED = 3  # applied correctly
    STATUS_APPLIED_WITH_CONFLICTS = 4  # applied but needs conflict resolution
    STATUS_ERROR = 5  # was not possible to apply the deltafile

    STATUS_CHOICES = (
        (STATUS_PENDING, 'PENDING'),
        (STATUS_BUSY, 'BUSY'),
        (STATUS_APPLIED, 'APPLIED'),
        (STATUS_APPLIED_WITH_CONFLICTS, 'APPLIED_WITH_CONFLICTS'),
        (STATUS_ERROR, 'ERROR'),
    )

    def file_path(instance, filename):
        return os.path.join(
            str(instance.project.id),
            'deltas',
            str(instance.id),
        )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True)
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES,
        default=STATUS_PENDING)
    file = models.FileField(upload_to=file_path)
    output = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


@receiver(models.signals.post_delete, sender=FileVersion)
def delete_file(sender, instance, *args, **kwargs):
    """Deletes physical file"""
    instance.stored_file.storage.delete(instance.stored_file.name)
