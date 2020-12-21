import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import JSONField
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db.models.signals import post_save
from django.urls import reverse
from django.dispatch import receiver

from qfieldcloud.core import utils


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

    def get_absolute_url(self):
        return reverse('user_overview', kwargs={
            'content_owner': self.username,
            'pk': self.pk})


# Automatically create a UserAccount instance when a user is created.
@receiver(post_save, sender=User)
def create_account(sender, instance, created, **kwargs):
    if created:
        UserAccount.objects.create(user=instance)


class UserAccount(models.Model):
    TYPE_COMMUNITY = 1
    TYPE_PRO = 2

    TYPE_CHOICES = (
        (TYPE_COMMUNITY, 'community'),
        (TYPE_PRO, 'pro'),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True)
    account_type = models.PositiveSmallIntegerField(
        choices=TYPE_CHOICES, default=TYPE_COMMUNITY)
    storage_limit_mb = models.PositiveIntegerField(default=100)
    db_limit_mb = models.PositiveIntegerField(default=25)
    synchronizations_per_months = models.PositiveIntegerField(default=30)

    def __str__(self):
        return self.TYPE_CHOICES[self.account_type][1]


class Organization(User):
    # TODO: add extra specific organization fields, like website url etc

    organization_owner = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='owner',
        limit_choices_to=models.Q(user_type=User.TYPE_USER))

    class Meta:
        verbose_name = 'organization'
        verbose_name_plural = 'organizations'

    def save(self, *args, **kwargs):
        if not self.id:
            self.user_type = self.TYPE_ORGANIZATION
        return super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('organization_overview', kwargs={
            'content_owner': self.username,
            'pk': self.pk})


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
        return self.name + ' (' + str(self.id) + ')' + ' owner: ' + self.owner.username

    def storage_size(self):
        return utils.get_s3_project_size(self.id)

    def get_absolute_url(self):
        return reverse('project_overview',
                       kwargs={'content_owner': self.owner.username,
                               'project': self.name,
                               'pk': self.pk})


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
        limit_choices_to=models.Q(user_type=User.TYPE_USER))
    role = models.PositiveSmallIntegerField(
        choices=ROLE_CHOICES, default=ROLE_READER)

    def __str__(self):
        return self.project.name + ': ' + self.collaborator.username


class Delta(models.Model):

    STATUS_PENDING = 1  # delta has been received, but have not started application
    STATUS_BUSY = 2  # currently being applied
    STATUS_APPLIED = 3  # applied correctly
    STATUS_CONFLICT = 4  # needs conflict resolution
    STATUS_NOT_APPLIED = 5
    STATUS_ERROR = 6  # was not possible to apply the delta

    STATUS_CHOICES = (
        (STATUS_PENDING, 'STATUS_PENDING'),
        (STATUS_BUSY, 'STATUS_BUSY'),
        (STATUS_APPLIED, 'STATUS_APPLIED'),
        (STATUS_CONFLICT, 'STATUS_CONFLICT'),
        (STATUS_NOT_APPLIED, 'STATUS_NOT_APPLIED'),
        (STATUS_ERROR, 'STATUS_ERROR'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deltafile_id = models.UUIDField()
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='deltas',
    )
    content = JSONField()
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES,
        default=STATUS_PENDING)
    output = JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.id) + ', project: ' + str(self.project.id)
