import uuid
import secrets
import string
import os

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import JSONField
from django.db.models.signals import post_save, post_delete
from django.db.models.aggregates import Count
from django.urls import reverse
from django.utils.translation import gettext as _
from django.dispatch import receiver

from qfieldcloud.core import utils, geodb_utils, validators


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
            validators.reserved_words_validator)
        self._meta.get_field('username').validators.append(
            validators.allowed_symbols_validator)
        self._meta.get_field('username').validators.append(
            validators.min_lenght_validator)
        self._meta.get_field('username').validators.append(
            validators.first_symbol_validator)

    def __str__(self):
        return self.username

    def get_absolute_url(self):
        return reverse('user_overview', kwargs={
            'content_owner': self.username,
            'pk': self.pk})

    @property
    def is_user(self):
        return self.user_type == User.TYPE_USER

    @property
    def is_organization(self):
        return self.user_type == User.TYPE_ORGANIZATION

    def can_modify(self, object):
        return object == self

    def can_upload_project_files(self, project) -> bool:
        # TODO check also for organization membership
        return project.owner == self

    def can_explore_project(self, project) -> bool:
        # TODO check also for organization membership
        return project.owner == self or not project.private

    def can_update_project_description(self, project) -> bool:
        # TODO check also for organization membership
        return project.owner == self


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
    bio = models.CharField(max_length=255, default='')
    workplace = models.CharField(max_length=255, default='')
    location = models.CharField(max_length=255, default='')
    twitter = models.CharField(max_length=255, default='')
    is_email_public = models.BooleanField(default=False)

    def __str__(self):
        return self.TYPE_CHOICES[self.account_type][1]


class Geodb(models.Model):

    def random_string():
        """ Generate random sting starting with a lowercase letter and then
        lowercase letters and digits"""

        first_letter = secrets.choice(string.ascii_lowercase)
        letters_and_digits = string.ascii_lowercase + string.digits
        secure_str = first_letter + ''.join(
            (secrets.choice(letters_and_digits) for i in range(15)))
        return secure_str

    def random_password():
        """ Generate secure random password composed of
        letters, digits and special characters"""

        password_characters = string.ascii_letters + string.digits + '!#$%&()*+,-.:;<=>?@[]_{}~'
        secure_str = ''.join(
            (secrets.choice(password_characters) for i in range(16)))
        return secure_str

    def default_hostname():
        # If geodb is running on the same machine we connect trough
        # the internal docker net
        if os.environ.get('GEODB_HOST') == 'localhost':
            return 'geodb'

    def default_port():
        # If geodb is running on the same machine we connect trough
        # the internal docker net
        if os.environ.get('GEODB_HOST') == 'localhost':
            return 5432

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True)

    username = models.CharField(
        blank=False, max_length=255, default=random_string)
    dbname = models.CharField(
        blank=False, max_length=255, default=random_string)
    hostname = models.CharField(
        blank=False, max_length=255, default=default_hostname)
    port = models.PositiveIntegerField(default=default_port)
    created_at = models.DateTimeField(auto_now_add=True)

    # The password is generated but not stored into the db
    password = random_password()

    def size(self):
        return geodb_utils.get_db_size(self)

    def __str__(self):
        return '{}\'s db account, dbname: {}, username: {}'.format(
            self.user.username, self.dbname, self.username)


# Automatically create a role and database when a Geodb object is created.
@receiver(post_save, sender=Geodb)
def create_geodb(sender, instance, created, **kwargs):
    if created:
        geodb_utils.create_role_and_db(instance)


@receiver(post_delete, sender=Geodb)
def delete_geodb(sender, instance, **kwargs):
    geodb_utils.delete_db_and_role(instance)


class Organization(User):

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

    def get_absolute_url(self):
        return reverse('member_details',
                       kwargs={'content_owner': self.organization,
                               'member': self.member.username,
                               'pk': self.pk})


class Project(models.Model):
    """Represent a QFieldcloud project.
    It corresponds to a directory on the file system.

    The owner of a project is an Organization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        validators=[validators.allowed_symbols_validator,
                    validators.min_lenght_validator,
                    validators.first_symbol_validator,
                    validators.reserved_words_validator],
        help_text=_('Project name. Should start with a letter and contain only letters, numbers, underscores and hyphens.')
    )

    description = models.TextField(blank=True)
    private = models.BooleanField(
        default=False,
        help_text='Projects that are not marked as private would be visible and editable to anyone.')
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    overwrite_conflicts = models.BooleanField(
        default=True,
        help_text=_('If enabled, QFieldCloud will automatically overwrite conflicts in this project. Disabling this will force the project manager to manually resolve all the conflicts.')
    )

    def __str__(self):
        return self.name + ' (' + str(self.id) + ')' + ' owner: ' + self.owner.username

    def storage_size(self):
        return utils.get_s3_project_size(self.id)

    def get_absolute_url(self):
        return reverse('project_overview',
                       kwargs={'username': self.owner.username,
                               'project': self.name})

    @property
    def files(self):
        return utils.get_project_files(self.id)

    @property
    def files_count(self):
        return utils.get_project_files_count(self.id)


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

    def get_absolute_url(self):
        return reverse('collaborator_details',
                       kwargs={'content_owner': self.project.owner.username,
                               'project': self.project.name,
                               'collaborator': self.collaborator.username,
                               'pk': self.pk,
                               'project_pk': self.project.pk})


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

    def get_status_summary(filters={}):
        rows = Delta.objects.filter(**filters).values('status').annotate(count=Count('status')).order_by()

        rows_as_dict = {}
        for r in rows:
            rows_as_dict[r['status']] = r['count']

        counts = {}
        for status, _name in Delta.STATUS_CHOICES:
            counts[status] = rows_as_dict.get(status, 0)

        return counts


class Exportation(models.Model):
    STATUS_PENDING = 1  # Export has been requested, but not yet started
    STATUS_BUSY = 2  # Currently being exported
    STATUS_EXPORTED = 3  # Export finished
    STATUS_ERROR = 4  # was not possible to export the project

    STATUS_CHOICES = (
        (STATUS_PENDING, 'STATUS_PENDING'),
        (STATUS_BUSY, 'STATUS_BUSY'),
        (STATUS_EXPORTED, 'STATUS_EXPORTED'),
        (STATUS_ERROR, 'STATUS_ERROR'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='exports',
    )

    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES,
        default=STATUS_PENDING)
    exportlog = JSONField(null=True)
    output = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
