import logging
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, cast

import django_cryptography.fields
from deprecated import deprecated
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import transaction
from django.db.models import Case, Exists, F, OuterRef, Q
from django.db.models import Value as V
from django.db.models import When
from django.db.models.aggregates import Count, Sum
from django.db.models.fields.json import JSONField
from django.urls import reverse_lazy
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from model_utils.managers import InheritanceManager, InheritanceManagerMixin
from qfieldcloud.core import geodb_utils, utils, validators
from qfieldcloud.core.utils2 import storage
from qfieldcloud.subscription.exceptions import ReachedMaxOrganizationMembersError
from timezone_field import TimeZoneField

# http://springmeblog.com/2018/how-to-implement-multiple-user-types-with-django/

logger = logging.getLogger(__name__)


class PersonQueryset(models.QuerySet):
    """Adds for_project(user) method to the user's querysets, allowing to filter only users part of a project.

    Users are annotated with the user's project role (`project_role`) and the origin of this role (`project_role_origin`).
    If the project is public, it will return only the directly collaborated users.

    Args:
        project:               project to find users for

    Usage:
    ```
    # List all users that are involved in OpenKebabMap.
    Persons.object.for_project(OpenKebabMap)
    ```

    Note:
    This query is very similar to `ProjectQueryset.for_user`, don't forget to update it too.
    """

    def for_project(self, project: "Project", skip_invalid: bool):
        count_collaborators = Count(
            "project_roles__project__collaborators",
            filter=Q(
                project_roles__project__collaborators__collaborator__type=User.Type.PERSON
            ),
        )

        is_public_q = Q(project_roles__project__is_public=True)
        is_person_q = Q(project_roles__project__owner__type=User.Type.PERSON)
        is_org_q = Q(project_roles__project__owner__type=User.Type.ORGANIZATION)
        is_org_member_q = Q(
            project_roles__project__owner__type=User.Type.ORGANIZATION
        ) & Exists(
            Organization.objects.of_user(OuterRef("project_roles__user"))
            .select_related(None)
            .filter(id=OuterRef("project_roles__project__owner"))
        )

        max_premium_collaborators_per_private_project_q = Q(
            project_roles__project__owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project=V(
                -1
            )
        ) | Q(
            project_roles__project__owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project__gte=count_collaborators
        )

        project_role_is_valid_condition_q = is_public_q | (
            max_premium_collaborators_per_private_project_q
            & (is_person_q | (is_org_q & is_org_member_q))
        )

        qs = (
            self.defer("project_roles__project_id", "project_roles__project_id")
            .filter(
                project_roles__project=project,
            )
            .select_related("useraccount")
            .annotate(
                project_role=F("project_roles__name"),
                project_role_origin=F("project_roles__origin"),
                project_role_is_valid=Case(
                    When(project_role_is_valid_condition_q, then=True), default=False
                ),
            )
        )

        if skip_invalid:
            qs = qs.filter(project_role_is_valid=True)

        return qs

    def for_organization(self, organization: "Organization"):
        qs = (
            self.defer(
                "organization_roles__user_id",
                "organization_roles__organization_id",
            )
            .filter(
                type=User.Type.PERSON,
                organization_roles__organization=organization,
            )
            .annotate(
                organization_role=F("organization_roles__name"),
                organization_role_origin=F("organization_roles__origin"),
                organization_role_is_public=F("organization_roles__is_public"),
            )
        )

        return qs

    def for_team(self, team: "Team"):
        permissions_config = [
            # Direct ownership of the organization
            (
                Exists(
                    Team.objects.filter(
                        pk=team.pk,
                        team_organization__organization_owner=OuterRef("pk"),
                    )
                ),
                V(TeamMember.Roles.ADMIN),
            ),
            # Team membership
            (
                Exists(
                    TeamMember.objects.filter(
                        team=team,
                        member=OuterRef("pk"),
                    )
                ),
                V(TeamMember.Roles.MEMBER),
            ),
        ]

        qs = self.annotate(
            membership_role=Case(
                *[When(perm[0], perm[1]) for perm in permissions_config],
                default=None,
                output_field=models.CharField(),
            ),
        )
        qs = qs.exclude(membership_role__isnull=True)

        return qs

    def for_entity(self, entity: "User"):
        """Returns all users grouped in given entity (any type)

        Internally calls for_team or for_organization depending on the entity."""

        if entity.type == User.Type.PERSON:
            return self.filter(pk=entity.pk)

        if entity.type == User.Type.TEAM:
            return self.for_team(cast(Team, entity))

        if entity.type == User.Type.ORGANIZATION:
            return self.for_organization(cast(Organization, entity))

        raise RuntimeError(f"Unsupported entity : {entity}")


class UserManager(InheritanceManagerMixin, DjangoUserManager):
    # NOTE you should never have `select_related("user")` if you want the polymorphism to work.
    # tried with `select_related("user__person")`, or all child tables at once, but it's not working either
    def get_queryset(self):
        return super().get_queryset().select_subclasses()


class PersonManager(UserManager):
    def get_queryset(self):
        return PersonQueryset(self.model, using=self._db)

    def for_project(self, project: "Project", skip_invalid: bool = False):
        return self.get_queryset().for_project(project, skip_invalid)

    def for_organization(self, organization):
        return self.get_queryset().for_organization(organization)

    def for_team(self, entity):
        return self.get_queryset().for_team(entity)

    def for_entity(self, entity):
        return self.get_queryset().for_entity(entity)


class User(AbstractUser):
    """User model. Used as base for organizations and teams too.

    Args:
        AbstractUser (AbstractUser): the django's abstract user base

    Returns:
        User: the user instance

    Note:
        If you add validators in the constructor, note they will be added multiple times for each class that extends User.
    """

    objects = UserManager()

    class Type(models.IntegerChoices):
        PERSON = (1, _("Person"))
        ORGANIZATION = (2, _("Organization"))
        TEAM = (3, _("Team"))

    """Define username here, so we can avoid multiple validators from the constructor. Check the class notes."""
    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."
        ),
        validators=[
            RegexValidator(
                r"^[-a-zA-Z0-9_]+$",
                "Only letters, numbers, underscores or hyphens are allowed.",
            ),
            RegexValidator(r"^[a-zA-Z].*$", _("The name must begin with a letter.")),
            RegexValidator(
                r"^.{3,}$", _("The name must be at least 3 characters long.")
            ),
            validators.reserved_words_validator,
        ],
        error_messages={
            "unique": _("A user with that username already exists."),
        },
    )

    type = models.PositiveSmallIntegerField(
        choices=Type.choices, default=Type.PERSON, editable=False
    )

    def __str__(self):
        return self.username

    def get_absolute_url(self):
        if self.type == User.Type.TEAM:
            team = Team.objects.get(pk=self.pk)
            return reverse_lazy(
                "settings_teams_edit",
                kwargs={
                    "username": team.team_organization.username,
                    "teamname": team.teamname,
                },
            )
        else:
            return reverse_lazy("profile_overview", kwargs={"username": self.username})

    @property
    def is_person(self):
        return self.type == User.Type.PERSON

    @property
    def is_organization(self):
        return self.type == User.Type.ORGANIZATION

    @property
    def is_team(self):
        return self.type == User.Type.TEAM

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def username_with_full_name(self) -> str:
        full_name = self.full_name.strip()

        if full_name:
            return f"{self.username} ({full_name})"
        else:
            return self.username

    @property
    def has_geodb(self) -> bool:
        return hasattr(self, "geodb")

    def save(self, *args, **kwargs):
        from qfieldcloud.subscription.models import get_subscription_model

        Subscription = get_subscription_model()

        # if the user is created, we need to create a user account
        if self._state.adding and self.type != User.Type.TEAM:
            skip_account_creation = kwargs.pop("skip_account_creation", False)

            with transaction.atomic():
                super().save(*args, **kwargs)

                if not skip_account_creation:
                    account, _created = UserAccount.objects.get_or_create(user=self)
                    Subscription.get_or_create_current_subscription(account)
        else:
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.type != User.Type.TEAM:
            storage.delete_user_avatar(self)

        super().delete(*args, **kwargs)

    class Meta:
        base_manager_name = "objects"
        verbose_name = "user"
        verbose_name_plural = "users"

    #     # TODO Django 4.0 convert to functional unique constraint, see https://docs.djangoproject.com/en/4.0/ref/models/constraints/#expressions
    #     constraints = [
    #         # the uniqueness is guaranteed by username's unqiue index anyway
    #         # since Django has some annoying checks if `username` is unique, better sacrifice
    #         # some megabytes with two separate indexes for `username` and `UPPER(username)`
    #         UniqueConstraint(
    #             Upper("username"),
    #             name="core_user_username_uppercase"
    #         )
    #     ]


class Person(User):
    """Individual users in QFieldCloud."""

    objects = PersonManager()

    # The number of invitations the user can send.
    # NOTE the limit was developed during the beta phase and to prevent going over the email quota per hour.
    remaining_invitations = models.PositiveIntegerField(
        default=3,
        help_text=_("Remaining invitations that can be sent by the user himself."),
    )

    # The number of trial organizations the user can create.
    remaining_trial_organizations = models.PositiveIntegerField(
        default=0,
        help_text=_("Remaining trial organizations the user can create."),
    )

    # Whether the user agreed to subscribe for the newsletter
    has_newsletter_subscription = models.BooleanField(default=False)

    # Whether the user has accepted the Terms of Service
    has_accepted_tos = models.BooleanField(default=False)

    class Meta:
        verbose_name = "person"
        verbose_name_plural = "people"

    def save(self, *args, **kwargs):
        self.type = User.Type.PERSON
        return super().save(*args, **kwargs)


class UserAccount(models.Model):

    NOTIFS_IMMEDIATELY = timedelta(minutes=0)
    NOTIFS_HOURLY = timedelta(hours=1)
    NOTIFS_DAILY = timedelta(days=1)
    NOTIFS_WEEKLY = timedelta(weeks=1)
    NOTIFS_DISABLED = None
    NOTIFS_CHOICES = (
        (NOTIFS_IMMEDIATELY, _("Immediately")),
        (NOTIFS_HOURLY, _("Hourly")),
        (NOTIFS_DAILY, _("Daily")),
        (NOTIFS_WEEKLY, _("Weekly")),
        (NOTIFS_DISABLED, _("Disabled")),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)

    # These will be moved one day to the package. We don't touch for now (they are only used
    # in some tests)
    db_limit_mb = models.PositiveIntegerField(default=25)
    is_geodb_enabled = models.BooleanField(
        default=False,
        help_text=_("Whether the account has the option to create a GeoDB."),
    )

    bio = models.CharField(max_length=255, default="", blank=True)
    company = models.CharField(max_length=255, default="", blank=True)
    location = models.CharField(max_length=255, default="", blank=True)
    twitter = models.CharField(max_length=255, default="", blank=True)
    is_email_public = models.BooleanField(default=False)
    avatar_uri = models.CharField(_("Profile Picture URI"), max_length=255, blank=True)
    timezone = TimeZoneField(default="Europe/Zurich", choices_display="WITH_GMT_OFFSET")

    notifs_frequency = models.DurationField(
        verbose_name=_("Email frequency for notifications"),
        choices=NOTIFS_CHOICES,
        default=NOTIFS_DISABLED,
        null=True,
        blank=True,
    )

    @property
    def current_subscription(self):
        from qfieldcloud.subscription.models import get_subscription_model

        Subscription = get_subscription_model()
        return Subscription.get_or_create_current_subscription(self)

    @property
    @deprecated("Use `current_subscription` instead")
    def active_subscription(self):
        return self.current_subscription()

    @property
    def upcoming_subscription(self):
        from qfieldcloud.subscription.models import get_subscription_model

        Subscription = get_subscription_model()
        return Subscription.get_upcoming_subscription(self)

    @property
    def avatar_url(self):
        if self.avatar_uri:
            return reverse_lazy(
                "public_files",
                kwargs={"filename": self.avatar_uri},
            )
        else:
            return None

    @property
    @deprecated("Use `UserAccount().storage_used_bytes` instead")
    # TODO delete this method after refactoring tests so it's no longer used there
    def storage_used_mb(self) -> float:
        """Returns the storage used in MB"""
        return self.storage_used_bytes / 1000 / 1000

    @property
    def storage_used_bytes(self) -> float:
        """Returns the storage used in bytes"""
        used_quota = (
            self.user.projects.aggregate(sum_bytes=Sum("file_storage_bytes"))[
                "sum_bytes"
            ]
            # if there are no projects, the value will be `None`
            or 0
        )

        return used_quota

    @property
    @deprecated("Use `UserAccount().storage_free_bytes` instead")
    # TODO delete this method after refactoring tests so it's no longer used there
    def storage_free_mb(self) -> float:
        """Returns the storage quota left in MB (quota from account and packages minus storage of all owned projects)"""

        return self.storage_free_bytes / 1000 / 1000

    @property
    def storage_free_bytes(self) -> float:
        """Returns the storage quota left in bytes (quota from account and packages minus storage of all owned projects)"""

        return (
            self.current_subscription.active_storage_total_bytes
            - self.storage_used_bytes
        )

    @property
    def storage_used_ratio(self) -> float:
        """Returns the storage used in fraction of the total storage"""
        if self.current_subscription.active_storage_total_bytes > 0:
            return min(
                self.storage_used_bytes
                / self.current_subscription.active_storage_total_bytes,
                1,
            )
        else:
            return 1

    @property
    def storage_free_ratio(self) -> float:
        """Returns the storage used in fraction of the total storage"""
        return 1 - self.storage_used_ratio

    @property
    def has_premium_support(self) -> bool:
        """A user has premium support if they have an active premium subscription plan or a at least one organization that they have admin role."""
        subscription = self.current_subscription
        if subscription.plan.is_premium:
            return True

        if self.user.is_organization:
            return False

        if (
            Organization.objects.of_user(self.user)
            .filter(
                membership_role=OrganizationMember.Roles.ADMIN,
            )
            .count()
        ):
            return True

        return False

    def __str__(self) -> str:
        return f"{self.user.username_with_full_name} ({self.__class__.__name__})"


def random_string() -> str:
    """Generate random sting starting with a lowercase letter and then
    lowercase letters and digits"""

    first_letter = secrets.choice(string.ascii_lowercase)
    letters_and_digits = string.ascii_lowercase + string.digits
    secure_str = first_letter + "".join(
        secrets.choice(letters_and_digits) for i in range(15)
    )
    return secure_str


def random_password() -> str:
    """Generate secure random password composed of
    letters, digits and special characters"""

    password_characters = (
        string.ascii_letters + string.digits + "!#$%&()*+,-.:;<=>?@[]_{}~"
    )
    secure_str = "".join(secrets.choice(password_characters) for i in range(16))
    return secure_str


def default_hostname() -> str:
    return os.environ.get("GEODB_HOST")


def default_port() -> str:
    return os.environ.get("GEODB_PORT")


class Geodb(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    username = models.CharField(blank=False, max_length=255, default=random_string)
    dbname = models.CharField(blank=False, max_length=255, default=random_string)
    hostname = models.CharField(blank=False, max_length=255, default=default_hostname)
    port = models.PositiveIntegerField(default=default_port)
    created_at = models.DateTimeField(auto_now_add=True)

    # The password is generated but not stored into the db
    password = ""
    last_geodb_error = None

    def __init__(self, *args, password="", **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.password = password

        if not self.password:
            self.password = random_password()

    def size(self):
        try:
            return geodb_utils.get_db_size(self)
        except Exception as err:
            self.last_geodb_error = str(err)
            return None

    def __str__(self):
        return "{}'s db account, dbname: {}, username: {}".format(
            self.user.username, self.dbname, self.username
        )

    def save(self, *args, **kwargs):
        created = self._state.adding
        super().save(*args, **kwargs)
        # Automatically create a role and database when a Geodb object is created.
        if created:
            geodb_utils.create_role_and_db(self)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        # Automatically delete role and database when a Geodb object is deleted.
        geodb_utils.delete_db_and_role(self.dbname, self.username)


class OrganizationQueryset(models.QuerySet):
    """Adds of_user(user) method to the organization's querysets, allowing to filter only organization related to that user.

    Organizations are annotated with the user's role (`membership_role`), the origin of this role (`membership_role_origin`)
    and whether it is public (`membership_is_public`).

    Args:
        user:               user to check membership for
    """

    class RoleOrigins(models.TextChoices):
        ORGANIZATIONOWNER = "organization_owner", _("Organization owner")
        ORGANIZATIONMEMBER = "organization_member", _("Organization member")

    def of_user(self, user):
        qs = (
            self.defer("membership_roles__user_id", "membership_roles__organization_id")
            .filter(
                membership_roles__user=user,
            )
            .annotate(
                membership_role=F("membership_roles__name"),
                membership_role_origin=F("membership_roles__origin"),
                membership_role_is_public=F("membership_roles__is_public"),
            )
        )

        return qs


class OrganizationManager(UserManager):
    def get_queryset(self):
        return OrganizationQueryset(self.model, using=self._db)

    def of_user(self, user):
        return self.get_queryset().select_related("useraccount").of_user(user)


class Organization(User):
    class Meta:
        verbose_name = "organization"
        verbose_name_plural = "organizations"

    objects = OrganizationManager()

    organization_owner = models.ForeignKey(
        # NOTE should be Person, but Django sometimes has troubles with Person/User (e.g. Form.full_clean()), see #514 #515
        User,
        on_delete=models.CASCADE,
        related_name="owned_organizations",
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

    is_initially_trial = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        # NOTE should be Person, but Django sometimes has troubles with Person/User (e.g. Form.full_clean()), see #514 #515
        User,
        on_delete=models.CASCADE,
        related_name="created_organizations",
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    def active_users(self, period_since: datetime, period_until: datetime):
        """Returns the queryset of active users in the given time interval.

        Active users are users triggering a job or pushing a delta on a project owned by the organization.

        Args:
            period_since (datetime): inclusive beginning of the interval
            period_until (datetime): inclusive end of the interval
        """
        assert period_since
        assert period_until

        users_with_delta = (
            Delta.objects.filter(
                project__in=self.projects.all(),
                created_at__gte=period_since,
                created_at__lte=period_until,
            )
            .values_list("created_by_id", flat=True)
            .distinct()
        )
        users_with_jobs = (
            Job.objects.filter(
                project__in=self.projects.all(),
                created_at__gte=period_since,
                created_at__lte=period_until,
            )
            .values_list("created_by_id", flat=True)
            .distinct()
        )

        return Person.objects.filter(
            is_staff=False,
        ).filter(Q(id__in=users_with_delta) | Q(id__in=users_with_jobs))

    def save(self, *args, **kwargs):
        self.type = User.Type.ORGANIZATION
        if getattr(self, "created_by", None) is not None:
            self.created_by = self.created_by
        else:
            self.created_by = self.organization_owner
        return super().save(*args, **kwargs)


class OrganizationMemberQueryset(models.QuerySet):
    @transaction.atomic
    def delete(self, *args, **kwargs):
        team_total, team_summary = TeamMember.objects.filter(
            team__team_organization__in=self.values_list("organization"),
            member__in=self.values_list("member"),
        ).delete()

        org_total, org_summary = super().delete(*args, **kwargs)

        total = org_total + team_total
        summary = {**org_summary, **team_summary}

        return total, summary


class OrganizationMember(models.Model):

    objects = OrganizationMemberQueryset.as_manager()

    class Roles(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "member"],
                name="organization_organization_member_uniq",
            )
        ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(type=User.Type.ORGANIZATION),
        related_name="members",
    )
    member = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )
    role = models.CharField(max_length=10, choices=Roles.choices, default=Roles.MEMBER)

    is_public = models.BooleanField(default=False)

    def __str__(self):
        return self.organization.username + ": " + self.member.username

    def clean(self) -> None:
        if self.organization.organization_owner == self.member:
            raise ValidationError(_("Cannot add the organization owner as a member."))

        max_organization_members = (
            self.organization.useraccount.current_subscription.plan.max_organization_members
        )
        if (
            max_organization_members > -1
            and self.organization.members.count() >= max_organization_members
        ):
            raise ReachedMaxOrganizationMembersError

        return super().clean()

    @transaction.atomic
    def delete(self, *args, **kwargs) -> None:
        super().delete(*args, **kwargs)

        TeamMember.objects.filter(
            team__team_organization=self.organization,
            member=self.member,
        ).delete()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationRolesView(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        related_name="organization_roles",
    )
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.DO_NOTHING,
        related_name="membership_roles",
    )
    name = models.CharField(max_length=100, choices=OrganizationMember.Roles.choices)
    origin = models.CharField(
        max_length=100, choices=OrganizationQueryset.RoleOrigins.choices
    )
    is_public = models.BooleanField()

    class Meta:
        db_table = "organizations_with_roles_vw"
        managed = False


class Team(User):

    team_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="teams",
    )

    class Meta:
        verbose_name = "team"
        verbose_name_plural = "teams"

    def save(self, *args, **kwargs):
        self.type = User.Type.TEAM
        return super().save(*args, **kwargs)

    @property
    def teamname(self):
        return self.username.replace(f"@{self.team_organization.username}/", "")


class TeamMember(models.Model):
    class Roles(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "member"],
                name="team_team_member_uniq",
            )
        ]

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(type=User.Type.TEAM),
        related_name="members",
    )
    member = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

    def clean(self) -> None:
        if (
            not self.team.team_organization.members.filter(member=self.member).exists()
            and self.team.team_organization.organization_owner != self.member
        ):
            raise ValidationError(
                _("Cannot add team member that is not an organization member.")
            )

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.team.username + ": " + self.member.username


class ProjectQueryset(models.QuerySet):
    """Adds for_user(user) method to the project's querysets, allowing to filter only projects visible to that user.

    Projects are annotated with the user's role (`user_role`) and the origin of this role (`user_role_origin`).

    Args:
        user:               user to check permission for

    Usage:
    ```
    # List Olivier's projects that are visible to Ivan (olivier/ivan are User instances)
    olivier.projects.for_user(ivan)
    ```

    Note:
    This query is very similar to `PersonQueryset.for_project`, don't forget to update it too.
    """

    class RoleOrigins(models.TextChoices):
        PROJECTOWNER = "project_owner", _("Project owner")
        ORGANIZATIONOWNER = "organization_owner", _("Organization owner")
        ORGANIZATIONADMIN = "organization_admin", _("Organization admin")
        COLLABORATOR = "collaborator", _("Collaborator")
        TEAMMEMBER = "team_member", _("Team member")
        PUBLIC = "public", _("Public")

    def for_user(self, user: "User", skip_invalid: bool = False):
        count = Count(
            "collaborators",
            filter=Q(collaborators__collaborator__type=User.Type.PERSON),
        )

        is_public_q = Q(is_public=True)
        is_person_q = Q(owner__type=User.Type.PERSON)
        is_org_q = Q(owner__type=User.Type.ORGANIZATION)
        is_org_member_q = Q(owner__type=User.Type.ORGANIZATION) & Exists(
            Organization.objects.of_user(user)
            .select_related(None)
            .filter(id=OuterRef("owner"))
        )
        max_premium_collaborators_per_private_project_q = Q(
            owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project=V(
                -1
            )
        ) | Q(
            owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project__gte=count
        )

        # Assemble the condition
        is_valid_user_role_q = is_public_q | (
            max_premium_collaborators_per_private_project_q
            & (is_person_q | (is_org_q & is_org_member_q))
        )

        qs = (
            self.defer("user_roles__user_id", "user_roles__project_id")
            .filter(
                user_roles__user=user,
            )
            .select_related("owner")
            .annotate(
                user_role=F("user_roles__name"),
                user_role_origin=F("user_roles__origin"),
                user_role_is_valid=Case(
                    When(is_valid_user_role_q, then=True), default=False
                ),
                user_role_is_incognito=F("user_roles__is_incognito"),
            )
        )

        if skip_invalid:
            qs = qs.filter(user_role_is_valid=True)

        return qs


class Project(models.Model):
    """Represent a QFieldcloud project.
    It corresponds to a directory on the file system.

    The owner of a project is an Organization.
    """

    # NOTE the status is NOT stored in the db, because it might be refactored
    class Status(models.TextChoices):
        OK = "ok", _("Ok")
        BUSY = "busy", _("Busy")
        FAILED = "failed", _("Failed")

    class StatusCode(models.TextChoices):
        OK = "ok", _("Ok")
        FAILED_PROCESS_PROJECTFILE = "failed_process_projectfile", _(
            "Failed process projectfile"
        )
        TOO_MANY_COLLABORATORS = "too_many_collaborators", _("Too many collaborators")

    objects = ProjectQueryset.as_manager()

    _status_code = StatusCode.OK

    class Meta:
        ordering = ["owner__username", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="project_owner_name_uniq"
            )
        ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                r"^[a-zA-Z0-9-_\.]+$",
                _("Only letters, numbers, underscores, hyphens and dots are allowed."),
            )
        ],
        help_text=_(
            _("Only letters, numbers, underscores, hyphens and dots are allowed.")
        ),
    )

    description = models.TextField(blank=True)
    project_filename = models.TextField(blank=True, null=True)
    project_details = models.JSONField(blank=True, null=True)
    is_public = models.BooleanField(
        default=False,
        help_text=_(
            "Projects marked as public are visible to (but not editable by) anyone."
        ),
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="projects",
        limit_choices_to=models.Q(type__in=[User.Type.PERSON, User.Type.ORGANIZATION]),
        help_text=_(
            "The project owner can be either you or any of the organization you are member of."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # These cache stats of the S3 storage. These can be out of sync, and should be
    # refreshed whenever retrieving/uploading files by passing `project.save(recompute_storage=True)`
    file_storage_bytes = models.PositiveBigIntegerField(default=0)

    # NOTE we can track only the file based layers, WFS, WMS, PostGIS etc are impossible to track
    data_last_updated_at = models.DateTimeField(blank=True, null=True)
    data_last_packaged_at = models.DateTimeField(blank=True, null=True)

    last_package_job = models.ForeignKey(
        "PackageJob",
        on_delete=models.SET_NULL,
        related_name="last_job_of",
        null=True,
        blank=True,
    )

    repackaging_cache_expire = models.DurationField(
        default=timedelta(minutes=60),
        validators=[MinValueValidator(timedelta(minutes=1))],
    )

    overwrite_conflicts = models.BooleanField(
        default=True,
        help_text=_(
            "If enabled, QFieldCloud will automatically overwrite conflicts in this project. Disabling this will force the project manager to manually resolve all the conflicts."
        ),
    )
    thumbnail_uri = models.CharField(
        _("Thumbnail Picture URI"), max_length=255, blank=True
    )

    # Duplicating logic from the plan's storage_keep_versions
    # so that users use less file versions (therefore storage)
    # than as per their plan's default on specific projects.
    # WARNING: If storage_keep_versions == 0, it will delete all file versions (hence the file itself) !
    storage_keep_versions = models.PositiveIntegerField(
        _("File versions to keep"),
        help_text=_(
            "Use this value to limit the maximum number of file versions. If empty, your current plan's default will be used. Available to Premium users only."
        ),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )

    @property
    def owner_aware_storage_keep_versions(self) -> int:
        """Determine the storage versions to keep based on the owner's subscription plan and project settings.

        Returns:
            int: the number of file versions, should be always greater than 1
        """
        subscription = self.owner.useraccount.current_subscription

        if subscription.plan.is_premium:
            keep_count = (
                self.storage_keep_versions or subscription.plan.storage_keep_versions
            )
        else:
            keep_count = subscription.plan.storage_keep_versions

        assert keep_count >= 1, "Ensure that we don't destroy all file versions!"

        return keep_count

    @property
    def thumbnail_url(self):
        if self.thumbnail_uri:
            return reverse_lazy(
                "project_metafiles",
                kwargs={"projectid": self.id, "filename": self.thumbnail_uri[51:]},
            )
        else:
            return None

    def get_absolute_url(self):
        return reverse_lazy(
            "project_overview",
            kwargs={"username": self.owner.username, "project": self.name},
        )

    def __str__(self):
        return self.name + " (" + str(self.id) + ")" + " owner: " + self.owner.username

    @property
    def attachment_dirs(self) -> List[str]:
        """Returns a list of configured attachment dirs for the project.

        Attachment dir is a special directory in the QField infrastructure that holds attachment files
        such as images, pdf etc. By default "DCIM" is considered a attachment directory.

        TODO this function expects whether `attachment_dirs` key in project_details. However,
        neither the extraction from the projectfile, nor the configuration in QFieldSync are implemented.

        Returns:
            List[str]: A list configured attachment dirs for the project.
        """
        attachment_dirs = []

        if self.project_details and self.project_details.get("attachment_dirs"):
            attachment_dirs = self.project_details.get("attachment_dirs", [])

        if not attachment_dirs:
            attachment_dirs = ["DCIM"]

        return attachment_dirs

    @property
    def private(self) -> bool:
        # still used in the project serializer
        return not self.is_public

    @cached_property
    def files(self) -> List[utils.S3ObjectWithVersions]:
        """Gets all the files from S3 storage. This is potentially slow. Results are cached on the instance."""
        return list(utils.get_project_files_with_versions(self.id))

    @property
    @deprecated("Use `len(project.files)` instead")
    def files_count(self):
        return len(self.files)

    @property
    def users(self):
        return User.objects.for_project(self)

    @property
    def has_online_vector_data(self) -> Optional[bool]:
        """Returns None if project details or layers details are not available"""

        if not self.project_details:
            return None

        layers_by_id = self.project_details.get("layers_by_id")

        if layers_by_id is None:
            return None

        has_online_vector_layers = False

        for layer_data in layers_by_id.values():
            # NOTE QGIS 3.30.x returns "Vector", while previous versions return "VectorLayer"
            if layer_data.get("type_name") in (
                "VectorLayer",
                "Vector",
            ) and not layer_data.get("filename", ""):
                has_online_vector_layers = True
                break

        return has_online_vector_layers

    @property
    def can_repackage(self) -> bool:
        return True

    @property
    def needs_repackaging(self) -> bool:
        if (
            # if has_online_vector_data is None (happens when the project details are missing)
            # we assume there might be
            self.has_online_vector_data is False
            and self.data_last_updated_at
            and self.data_last_packaged_at
            and self.last_package_job is not None
        ):
            # if all vector layers are file based and have been packaged after the last update, it is safe to say there are no modifications
            return self.data_last_packaged_at < self.data_last_updated_at
        else:
            # if the project has online vector layers (PostGIS/WFS/etc) we cannot be sure if there are modification or not, so better say there are
            return True

    @property
    def problems(self) -> list[dict]:
        problems = []

        if not self.project_filename:
            problems.append(
                {
                    "layer": None,
                    "level": "error",
                    "code": "missing_projectfile",
                    "description": _("Missing QGIS project file (.qgs/.qgz)."),
                    "solution": _(
                        "Make sure a QGIS project file (.qgs/.qgz) is uploaded to QFieldCloud. Reupload the file if problem persists."
                    ),
                }
            )
        elif self.project_details:
            for layer_data in self.project_details.get("layers_by_id", {}).values():
                layer_name = layer_data.get("name")

                if layer_data.get("error_code") != "no_error":
                    problems.append(
                        {
                            "layer": layer_name,
                            "level": "warning",
                            "code": "layer_problem",
                            "description": _(
                                'Layer "{}" has an error with code "{}": {}'
                            ).format(
                                layer_name,
                                layer_data.get("error_code"),
                                layer_data.get("error_summary"),
                            ),
                            "solution": _(
                                'Check the last "process_projectfile" logs for more info and reupload the project files with the required changes.'
                            ),
                        }
                    )
                # the layer is missing a primary key, warn it is going to be read-only
                elif layer_data.get("layer_type_name") in ("VectorLayer", "Vector"):
                    if layer_data.get("qfc_source_data_pk_name") == "":
                        problems.append(
                            {
                                "layer": layer_name,
                                "level": "warning",
                                "code": "layer_problem",
                                "description": _(
                                    'Layer "{}" does not support the `primary key` attribute. The layer will be read-only on QField.'
                                ).format(
                                    layer_name,
                                ),
                                "solution": _(
                                    "To make the layer editable on QField, store the layer data in a GeoPackage or PostGIS layer, using a single column for the primary key."
                                ),
                            }
                        )
        else:
            problems.append(
                {
                    "layer": None,
                    "level": "error",
                    "code": "missing_project_details",
                    "description": _("Failed to parse metadata from project."),
                    "solution": _("Re-upload the QGIS project file (.qgs/.qgz)."),
                }
            )

        return problems

    @property
    def status(self) -> Status:
        # NOTE the status is NOT stored in the db, because it might be outdated
        if (
            self.jobs.filter(status__in=[Job.Status.QUEUED, Job.Status.STARTED])
        ).exists():
            return Project.Status.BUSY
        else:
            status = Project.Status.OK
            status_code = Project.StatusCode.OK
            max_premium_collaborators_per_private_project = (
                self.owner.useraccount.current_subscription.plan.max_premium_collaborators_per_private_project
            )

            # TODO use self.problems to get if there are project problems
            if not self.project_filename or not self.project_details:
                status = Project.Status.FAILED
                status_code = Project.StatusCode.FAILED_PROCESS_PROJECTFILE
            elif (
                not self.is_public
                and max_premium_collaborators_per_private_project != -1
                and max_premium_collaborators_per_private_project
                < self.direct_collaborators.count()
            ):
                status = Project.Status.FAILED
                status_code = Project.StatusCode.TOO_MANY_COLLABORATORS

            self._status_code = status_code
            return status

    @property
    def status_code(self) -> StatusCode:
        return self._status_code

    @property
    def storage_size_perc(self) -> float:
        if self.owner.useraccount.current_subscription.active_storage_total_bytes > 0:
            return (
                self.file_storage_bytes
                / self.owner.useraccount.current_subscription.active_storage_total_bytes
                * 100
            )
        else:
            return 100

    @property
    def direct_collaborators(self):
        if self.owner.is_organization:
            exclude_pks = [self.owner.organization.organization_owner_id]
        else:
            exclude_pks = [self.owner_id]

        return (
            self.collaborators.skip_incognito()
            .filter(
                collaborator__type=User.Type.PERSON,
            )
            .exclude(
                collaborator_id__in=exclude_pks,
            )
        )

    def delete(self, *args, **kwargs):
        if self.thumbnail_uri:
            storage.delete_project_thumbnail(self)
        super().delete(*args, **kwargs)

    @property
    def owner_can_create_job(self):
        # NOTE consider including in status refactoring

        from qfieldcloud.core.permissions_utils import (
            is_supported_regarding_owner_account,
        )

        return is_supported_regarding_owner_account(self)

    def check_can_be_created(self):
        from qfieldcloud.core.permissions_utils import (
            check_supported_regarding_owner_account,
        )

        check_supported_regarding_owner_account(self, ignore_online_layers=True)

    def clean(self) -> None:
        """
        Prevent creating new projects if the user is inactive or over quota
        """
        if self._state.adding:
            self.check_can_be_created()

        return super().clean()

    def save(self, recompute_storage=False, *args, **kwargs):
        self.clean()
        logger.info(f"Saving project {self}...")

        if recompute_storage:
            self.file_storage_bytes = storage.get_project_file_storage_in_bytes(self.id)

        # Ensure that the Project's storage_keep_versions is at least 1, and reflects the plan's default storage_keep_versions value.
        if not self.storage_keep_versions:
            self.storage_keep_versions = (
                self.owner.useraccount.current_subscription.plan.storage_keep_versions
            )

        assert (
            self.storage_keep_versions >= 1
        ), "If 0, storage_keep_versions mean that all file versions are deleted!"

        super().save(*args, **kwargs)


class ProjectCollaboratorQueryset(models.QuerySet):
    def validated(self, skip_invalid=False):
        """Annotates the queryset with `is_valid` and by default filters out all invalid memberships if `skip_invalid` is set to True.

        A membership to a private project is valid when the owning user plan has a
        `max_premium_collaborators_per_private_project` >= of the total count of project collaborators.

        Args:
            skip_invalid:   if true, invalid rows are removed"""
        count = Count(
            "project__collaborators",
            filter=Q(
                collaborator__type=User.Type.PERSON,
                # incognito users should never be counted
                is_incognito=False,
            ),
        )

        # Build the conditions with Q objects
        is_public_q = Q(project__is_public=True)
        is_team_collaborator = Q(collaborator__type=User.Type.TEAM)
        # max_premium_collaborators_per_private_project_q = current_subscription_q & (
        max_premium_collaborators_per_private_project_q = Q(
            project__owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project=V(
                -1
            )
        ) | Q(
            project__owner__useraccount__current_subscription_vw__plan__max_premium_collaborators_per_private_project__gte=count
        )

        # Assemble the condition
        is_valid_collaborator = (
            is_public_q
            | max_premium_collaborators_per_private_project_q
            | is_team_collaborator
        )

        # Annotate the queryset
        qs = self.annotate(
            is_valid=Case(When(is_valid_collaborator, then=True), default=False)
        )

        # Filter out invalid
        if skip_invalid:
            qs = qs.exclude(is_valid=False)

        return qs

    def skip_incognito(self):
        return self.filter(is_incognito=False)


class ProjectCollaborator(models.Model):
    class Roles(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MANAGER = "manager", _("Manager")
        EDITOR = "editor", _("Editor")
        REPORTER = "reporter", _("Reporter")
        READER = "reader", _("Reader")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "collaborator"],
                name="projectcollaborator_project_collaborator_uniq",
            )
        ]

    objects = ProjectCollaboratorQueryset.as_manager()

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="collaborators",
    )
    collaborator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(type__in=[User.Type.PERSON, User.Type.TEAM]),
    )
    role = models.CharField(max_length=10, choices=Roles.choices, default=Roles.READER)

    # whether the collaborator is incognito, e.g. shown in the UI and billed
    is_incognito = models.BooleanField(
        default=False,
        help_text=_(
            "If a collaborator is marked as incognito, they will work as normal, but will not be listed in the UI or accounted in the subscription as active users. Used to add OPENGIS.ch support members to projects."
        ),
    )

    # created by
    created_by = models.ForeignKey(
        # NOTE should be Person, but Django sometimes has troubles with Person/User (e.g. Form.full_clean()), see #514 #515
        User,
        on_delete=models.SET_NULL,
        related_name="+",
        limit_choices_to=models.Q(type=User.Type.PERSON),
        null=True,
        blank=True,
    )

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # created by
    updated_by = models.ForeignKey(
        # NOTE should be Person, but Django sometimes has troubles with Person/User (e.g. Form.full_clean()), see #514 #515
        User,
        on_delete=models.SET_NULL,
        related_name="+",
        limit_choices_to=models.Q(type=User.Type.PERSON),
        null=True,
        blank=True,
    )

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.project.name + ": " + self.collaborator.username

    def clean(self) -> None:
        if self.project.owner == self.collaborator:
            raise ValidationError(_("Cannot add the project owner as a collaborator."))

        if self.project.owner.is_organization:
            organization = Organization.objects.get(pk=self.project.owner.pk)
            if self.collaborator.is_person:
                members_qs = organization.members.filter(member=self.collaborator)

                if not members_qs.exists():
                    raise ValidationError(
                        _(
                            "Cannot add a user who is not a member of the organization as a project collaborator."
                        )
                    )
            elif self.collaborator.is_team:
                team_qs = organization.teams.filter(pk=self.collaborator)
                if not team_qs.exists():

                    raise ValidationError(_("Team does not exist."))

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectRolesView(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        related_name="project_roles",
    )
    project = models.ForeignKey(
        "Project",
        on_delete=models.DO_NOTHING,
        related_name="user_roles",
    )
    name = models.CharField(max_length=100, choices=ProjectCollaborator.Roles.choices)
    origin = models.CharField(
        max_length=100, choices=ProjectQueryset.RoleOrigins.choices
    )
    is_incognito = models.BooleanField()

    class Meta:
        db_table = "projects_with_roles_vw"
        managed = False


class Delta(models.Model):
    class Method(str, Enum):
        Create = "create"
        Delete = "delete"
        Patch = "patch"

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        STARTED = "started", _("Started")
        APPLIED = "applied", _("Applied")
        CONFLICT = "conflict", _("Conflict")
        NOT_APPLIED = "not_applied", _("Not_applied")
        ERROR = "error", _("Error")
        IGNORED = "ignored", _("Ignored")
        UNPERMITTED = "unpermitted", _("Unpermitted")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deltafile_id = models.UUIDField(db_index=True)
    client_id = models.UUIDField(null=False, db_index=True, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="deltas",
    )
    content = JSONField()
    last_status = models.CharField(
        choices=Status.choices,
        default=Status.PENDING,
        max_length=32,
        db_index=True,
    )
    last_feedback = JSONField(null=True)
    last_modified_pk = models.TextField(null=True)
    last_apply_attempt_at = models.DateTimeField(null=True)
    last_apply_attempt_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="uploaded_deltas",
    )
    old_geom = models.GeometryField(null=True, srid=4326, dim=4)
    new_geom = models.GeometryField(null=True, srid=4326, dim=4)

    jobs_to_apply = models.ManyToManyField(
        to="ApplyJob",
        through="ApplyJobDelta",
    )

    def __str__(self):
        return str(self.id) + ", project: " + str(self.project.id)

    @staticmethod
    def get_status_summary(filters={}):
        rows = (
            Delta.objects.filter(**filters)
            .values("last_status")
            .annotate(count=Count("last_status"))
            .order_by()
        )

        rows_as_dict = {}
        for r in rows:
            rows_as_dict[r["last_status"]] = r["count"]

        counts = {}
        for status, _name in Delta.Status.choices:
            counts[status] = rows_as_dict.get(status, 0)

        return counts

    @property
    def short_id(self):
        return str(self.id)[0:8]

    @property
    def method(self):
        return self.content.get("method")


class Job(models.Model):

    objects = InheritanceManager()

    class Type(models.TextChoices):
        PACKAGE = "package", _("Package")
        DELTA_APPLY = "delta_apply", _("Delta Apply")
        PROCESS_PROJECTFILE = "process_projectfile", _("Process QGIS Project File")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        QUEUED = "queued", _("Queued")
        STARTED = "started", _("Started")
        FINISHED = "finished", _("Finished")
        STOPPED = "stopped", _("Stopped")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    output = models.TextField(null=True)
    feedback = JSONField(null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    started_at = models.DateTimeField(blank=True, null=True, editable=False)
    finished_at = models.DateTimeField(blank=True, null=True, editable=False)
    docker_started_at = models.DateTimeField(blank=True, null=True, editable=False)
    docker_finished_at = models.DateTimeField(blank=True, null=True, editable=False)
    # the docker container ID of the QGIS worker that was executing the job
    container_id = models.CharField(
        max_length=64, default="", blank=True, db_index=True
    )

    @property
    def short_id(self) -> str:
        return str(self.id)[0:8]

    @property
    def fallback_output(self) -> str:
        # show whatever is the output if it is present
        if self.output:
            return ""

        if self.status == Job.Status.PENDING:
            return _(
                "The job is in pending status, it will be started as soon as there are available server resources."
            )
        elif self.status == Job.Status.QUEUED:
            return _(
                "The job is in queued status. Server resources are allocated and it will be started soon."
            )
        elif self.status == Job.Status.STARTED:
            return _("The job is in started status. Waiting for it to finish...")
        elif self.status == Job.Status.FINISHED:
            return _(
                "The job is in finished status. It finished successfully without any output."
            )
        elif self.status == Job.Status.STOPPED:
            return _("The job is in stopped status. Waiting to be continued...")
        elif self.status == Job.Status.FAILED:
            return _(
                "The job is in failed status. The execution failed due to server error. Please verify the project is configured properly and try again."
            )
        else:
            return _(
                "The job ended in unknown state. Please verify the project is configured properly, try again and contact QFieldCloud support for more information."
            )

    def check_can_be_created(self):
        from qfieldcloud.core.permissions_utils import (
            check_supported_regarding_owner_account,
        )

        check_supported_regarding_owner_account(self.project)

    def clean(self):
        if self._state.adding:
            self.check_can_be_created()

        return super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class PackageJob(Job):
    def save(self, *args, **kwargs):
        self.type = self.Type.PACKAGE
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Job: package"
        verbose_name_plural = "Jobs: package"


class ProcessProjectfileJob(Job):
    def check_can_be_created(self):
        # Alsways create jobs because they are cheap
        # and is always good to have updated metadata
        pass

    def save(self, *args, **kwargs):
        self.type = self.Type.PROCESS_PROJECTFILE
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Job: process QGIS project file"
        verbose_name_plural = "Jobs: process QGIS project file"


class ApplyJob(Job):

    deltas_to_apply = models.ManyToManyField(
        to=Delta,
        through="ApplyJobDelta",
    )

    overwrite_conflicts = models.BooleanField(
        help_text=_(
            "If enabled, QFieldCloud will automatically overwrite conflicts while applying deltas."
        ),
    )

    def save(self, *args, **kwargs):
        self.type = self.Type.DELTA_APPLY
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Job: apply"
        verbose_name_plural = "Jobs: apply"


class ApplyJobDelta(models.Model):
    apply_job = models.ForeignKey(ApplyJob, on_delete=models.CASCADE)
    delta = models.ForeignKey(Delta, on_delete=models.CASCADE)
    status = models.CharField(
        choices=Delta.Status.choices, default=Delta.Status.PENDING, max_length=32
    )
    feedback = JSONField(null=True)
    modified_pk = models.TextField(null=True)

    def __str__(self):
        return f"{self.apply_job_id}:{self.delta_id}"


class Secret(models.Model):
    class Type(models.TextChoices):
        PGSERVICE = "pgservice", _("pg_service")
        ENVVAR = "envvar", _("Environment Variable")

    name = models.TextField(
        max_length=255,
        validators=[
            RegexValidator(
                r"^[A-Z]+[A-Z0-9_]+$",
                _(
                    "Must start with a capital letter and followed by capital letters, numbers or underscores."
                ),
            )
        ],
        help_text=_(
            _(
                "Must start with a capital letter and followed by capital letters, numbers or underscores."
            ),
        ),
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="secrets"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="project_secrets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    value = django_cryptography.fields.encrypt(models.TextField())

    class Meta:
        ordering = ["project", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"], name="secret_project_name_uniq"
            )
        ]
