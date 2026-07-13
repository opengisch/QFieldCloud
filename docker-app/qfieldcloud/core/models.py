from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.gis.db import models
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import (
    RegexValidator,
)
from django.db import transaction
from django.db.models import Case, Exists, F, OuterRef, Q, When
from django.db.models import Value as V
from django.db.models.aggregates import Count, Sum
from django.db.models.fields.json import JSONField
from django.urls import reverse
from django.utils.translation import gettext as _
from encrypted_fields.fields import EncryptedTextField
from model_utils.managers import (
    InheritanceManagerMixin,
    InheritanceQuerySet,
)
from timezone_field import TimeZoneField

from qfieldcloud.core import validators
from qfieldcloud.core.fields import DynamicStorageFileField, QfcImageField, QfcImageFile
from qfieldcloud.project.enums import ProjectRoleOrigins
from qfieldcloud.subscription.exceptions import ReachedMaxOrganizationMembersError

if TYPE_CHECKING:
    from qfieldcloud.project.models import Project


# http://springmeblog.com/2018/how-to-implement-multiple-user-types-with-django/

logger = logging.getLogger(__name__)


class BasemapProvider(models.TextChoices):
    NONE = "none", _("No basemap")
    OSM = "osm", _("OpenStreetMap")
    CUSTOM = "custom", _("Custom XYZ basemap URL")


class BasemapStyle(models.TextChoices):
    STANDARD = "standard", _("Standard")
    GRAYSCALE_LIGHT = "grayscale_light", _("Grayscale Light")
    GRAYSCALE_DARK = "grayscale_dark", _("Grayscale Dark")


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

    def for_project(self, project: "Project", skip_invalid: bool) -> "PersonQueryset":
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
            Organization.objects.of_user(OuterRef("project_roles__user"))  # type: ignore
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

    def for_organization(self, organization: "Organization") -> "PersonQueryset":
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

    def for_team(self, team: "Team") -> "PersonQueryset":
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

    def for_entity(self, entity: "User") -> "PersonQueryset":
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

    def fast_search(self, username_or_email: str) -> "User":
        """Searches a user by `username` or `email` field

        Args:
            username_or_email: username or email to search for

        Returns:
            The user with that username or email.
        """
        return self.get(Q(username=username_or_email) | Q(email=username_or_email))


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
        the django's abstract user base

    Returns:
        the user instance

    Note:
        If you add validators in the constructor, note they will be added multiple times for each class that extends User.
    """

    # All projects that a user owns
    projects: models.QuerySet[Project]

    # The secrets that are assigned to a user.
    assigned_secrets: "models.QuerySet[Secret]"

    # The `UserAccount` stores non-critical user information such as avatar, bio, timezone settings etc.
    useraccount: UserAccount

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
            "Between 3 and 150 characters. Letters, digits, underscores '_' or hyphens '-' only. Must begin with a letter."
        ),
        validators=[
            RegexValidator(
                r"^[-a-zA-Z0-9_]+$",
                "Only letters, numbers, underscores '_' or hyphens '-' are allowed.",
            ),
            RegexValidator(r"^[a-zA-Z].*$", _("Must begin with a letter.")),
            RegexValidator(r"^.{3,}$", _("Must be at least 3 characters long.")),
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

    @property
    def is_person(self):
        return self.type == User.Type.PERSON

    @cached_property
    def public_id(self) -> str:
        return signing.dumps({"id": self.pk})

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

    class Meta(User.Meta):
        verbose_name = "person"
        verbose_name_plural = "people"

    def clean(self):
        if self.email:
            person_qs = self.__class__.objects.filter(email__iexact=self.email)

            if self.pk:
                person_qs = person_qs.exclude(pk=self.pk)

            if person_qs.exists():
                raise ValidationError(
                    _("This email is already taken by another user!").format(self.email)
                )

        return super().clean()

    def save(self, *args, **kwargs):
        self.type = User.Type.PERSON

        return super().save(*args, **kwargs)


def get_user_account_avatar_upload_to(
    instance: models.Model,
    filename: str,
) -> str:
    instance = cast(UserAccount, instance)
    filename_path = Path(filename)

    return f"account/{instance.user.username}/avatars/{filename_path.name}"


def get_user_account_avatar_download_from(
    instance: models.Model, value: QfcImageFile | None
) -> str | None:
    if not value:
        return None

    useraccount = cast(UserAccount, value.instance)

    return reverse(
        "filestorage_avatars",
        kwargs={
            "public_id": useraccount.user.public_id,
        },
    )


class UserAccountQuerySet(models.QuerySet):
    def get_by_natural_key(self, username: str) -> UserAccount:
        return self.get(user__username=username)


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

    objects = UserAccountQuerySet.as_manager()

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)

    # These will be moved one day to the package. We don't touch for now (they are only used
    # in some tests)
    db_limit_mb = models.PositiveIntegerField(default=25)

    bio = models.CharField(max_length=255, default="", blank=True)
    company = models.CharField(max_length=255, default="", blank=True)
    location = models.CharField(max_length=255, default="", blank=True)
    twitter = models.CharField(max_length=255, default="", blank=True)
    is_email_public = models.BooleanField(default=False)

    avatar = QfcImageField(
        _("Avatar Picture"),
        upload_to=get_user_account_avatar_upload_to,
        download_from=get_user_account_avatar_download_from,
        # the s3 storage has 1024 bytes (not chars!) limit: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        max_length=1024,
        null=True,
        blank=True,
    )

    timezone = TimeZoneField(
        default=settings.TIME_ZONE, choices_display="WITH_GMT_OFFSET"
    )

    notifs_frequency = models.DurationField(
        verbose_name=_("Email frequency for notifications"),
        choices=NOTIFS_CHOICES,
        default=NOTIFS_DISABLED,
        null=True,
        blank=True,
    )

    def natural_key(self) -> tuple:
        return self.user.natural_key()

    natural_key.dependencies = ["core.user"]  # type: ignore[attr-defined]

    @property
    def current_subscription(self):
        from qfieldcloud.subscription.models import get_subscription_model

        Subscription = get_subscription_model()
        return Subscription.get_or_create_current_subscription(self)

    @property
    def upcoming_subscription(self):
        from qfieldcloud.subscription.models import get_subscription_model

        Subscription = get_subscription_model()
        return Subscription.get_upcoming_subscription(self)

    @property
    def storage_used_bytes(self) -> int:
        """Returns the storage used in bytes"""
        from qfieldcloud.filestorage.models import File, FileVersion

        project_files_used_quota = (
            FileVersion.objects.filter(
                file__file_type=File.FileType.PROJECT_FILE,
                file__project__in=self.user.projects.all(),
            ).aggregate(sum_bytes=Sum("size"))["sum_bytes"]
            or 0
        )

        used_quota = project_files_used_quota

        return used_quota

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
            Organization.objects.of_user(self.user)  # type: ignore
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
    members: models.QuerySet["OrganizationMember"]
    organization_owner_id: int

    class Meta(User.Meta):
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
            period_since: inclusive beginning of the interval
            period_until: inclusive end of the interval
        """
        assert period_since
        assert period_until

        users_with_delta = (
            Delta.objects.filter(
                project__in=self.projects.all(),  # type: ignore
                created_at__gte=period_since,
                created_at__lte=period_until,
            )
            .values_list("created_by_id", flat=True)
            .distinct()
        )
        users_with_jobs = (
            Job.objects.filter(
                project__in=self.projects.all(),  # type: ignore
                created_at__gte=period_since,
                created_at__lte=period_until,
            )
            .values_list("created_by_id", flat=True)
            .distinct()
        )

        return Person.objects.filter(
            is_staff=False,
        ).filter(
            Q(id__in=users_with_delta)
            | Q(id__in=users_with_jobs)
            | Q(id=self.organization_owner_id)
        )

    def save(self, *args, **kwargs):
        self.type = User.Type.ORGANIZATION

        if getattr(self, "created_by", None) is not None:
            self.created_by = self.created_by
        else:
            self.created_by = self.organization_owner

        # if the org owner changes, adapt the memberships accordingly.
        if self.pk:
            old_org = Organization.objects.get(pk=self.pk)

            if old_org.organization_owner != self.organization_owner:
                with transaction.atomic():
                    # remove new owner from members.
                    OrganizationMember.objects.filter(
                        organization=self,
                        member=self.organization_owner,
                    ).delete()

                    # add old owner as admin member.
                    OrganizationMember.objects.update_or_create(
                        organization=self,
                        member=old_org.organization_owner,
                        defaults={
                            "role": OrganizationMember.Roles.ADMIN,
                            "created_by": self.created_by,
                            "updated_by": self.created_by,
                        },
                    )

        return super().save(*args, **kwargs)


class OrganizationMemberQueryset(models.QuerySet):
    def get_by_natural_key(
        self, organization_username: str, member_username: str
    ) -> "OrganizationMember":
        return self.get(
            organization__username=organization_username,
            member__username=member_username,
        )

    @transaction.atomic
    def delete(self, *args, **kwargs):
        # delete the team memberships of this deleted org member,
        # as it is no longer part of the organization.
        team_total, team_summary = TeamMember.objects.filter(
            team__team_organization__in=self.values_list("organization"),
            member__in=self.values_list("member"),
        ).delete()

        # delete the project collaborations of this deleted org member,
        # as it is no longer part of the organization.
        collab_total, collab_summary = ProjectCollaborator.objects.filter(
            project__owner__in=self.values_list("organization"),
            collaborator__in=self.values_list("member"),
        ).delete()

        org_total, org_summary = super().delete(*args, **kwargs)

        total = org_total + team_total + collab_total
        summary = {**org_summary, **team_summary, **collab_summary}

        return total, summary


class OrganizationMember(models.Model):
    objects = OrganizationMemberQueryset.as_manager()

    class Roles(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")

    ALL_ROLES = list(Roles)

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

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="created_organization_members",
        null=True,
        blank=True,
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="updated_organization_members",
        null=True,
        blank=True,
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.organization.username + ": " + self.member.username

    def natural_key(self) -> tuple:
        return self.organization.natural_key() + self.member.natural_key()

    natural_key.dependencies = ["core.organization", "core.user"]  # type: ignore[attr-defined]

    def clean(self) -> None:
        if self.organization.organization_owner == self.member:
            raise ValidationError(_("Cannot add the organization owner as a member."))

        subscription = self.organization.useraccount.current_subscription

        max_allowed_members = subscription.max_allowed_organization_members
        current_members = subscription.organization_members_count

        if max_allowed_members > -1 and current_members >= max_allowed_members:
            raise ReachedMaxOrganizationMembersError

        return super().clean()

    @transaction.atomic
    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        super().delete(*args, **kwargs)

        # delete the project collaborations of this deleted org member,
        # as it is no longer part of the organization.
        ProjectCollaborator.objects.filter(
            project__owner=self.organization,
            collaborator=self.member,
        ).delete()

        return TeamMember.objects.filter(
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

    class Meta(User.Meta):
        verbose_name = "team"
        verbose_name_plural = "teams"

    def save(self, *args, **kwargs):
        self.type = User.Type.TEAM
        return super().save(*args, **kwargs)

    @property
    def teamname(self):
        return self.username.replace(f"@{self.team_organization.username}/", "")

    @staticmethod
    def format_team_name(organization_name: str, team_name: str) -> str:
        """Returns the actual team username formatted as `@<organization_name>/<team_name>`."""
        if not team_name:
            raise ValueError("Team name is required.")

        return f"@{organization_name}/{team_name}"


class TeamMemberQuerySet(models.QuerySet):
    def get_by_natural_key(
        self, team_username: str, member_username: str
    ) -> "TeamMember":
        return self.get(
            team__username=team_username,
            member__username=member_username,
        )


class TeamMember(models.Model):
    objects = TeamMemberQuerySet.as_manager()

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

    def natural_key(self) -> tuple:
        return self.team.natural_key() + self.member.natural_key()

    natural_key.dependencies = ["core.team", "core.user"]  # type: ignore[attr-defined]

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

    ALL_ROLES = list(Roles)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "collaborator"],
                name="projectcollaborator_project_collaborator_uniq",
            )
        ]

    objects = ProjectCollaboratorQueryset.as_manager()

    project = models.ForeignKey(
        "project.Project",
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
                # for organizations-owned projects, the candidate collaborator
                # must be a member of the organization or the organization's owner
                if not (
                    organization.members.filter(member=self.collaborator).exists()  # type: ignore
                    or self.collaborator == organization.organization_owner
                ):
                    raise ValidationError(
                        _(
                            "Cannot add a user who is not a member of the organization as a project collaborator."
                        )
                    )
            elif self.collaborator.is_team:
                if not organization.teams.filter(pk=self.collaborator).exists():  # type: ignore
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
        "project.Project",
        on_delete=models.DO_NOTHING,
        related_name="user_roles",
    )
    name = models.CharField(max_length=100, choices=ProjectCollaborator.Roles.choices)
    origin = models.CharField(max_length=100, choices=ProjectRoleOrigins.choices)
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
        "project.Project",
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
    def get_status_summary(filters=None):
        if filters is None:
            filters = {}

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


class JobQuerySet(InheritanceQuerySet):
    def for_user(self, user: User) -> models.QuerySet[Job]:
        """Returns the jobs applicable to the user. If the user has assigned secrets, only jobs triggered by the user are returned.

        Args:
            user: The user to check for.

        Returns:
            The jobs for the user.
        """
        has_assigned_to_current_user_project_secrets = (
            Secret.objects.assigned_for_user(  # type: ignore[attr-defined]
                user=user,
            )
            .filter(assigned_to__isnull=False)
            .exists()
        )

        jobs_qs = self
        if has_assigned_to_current_user_project_secrets:
            jobs_qs = jobs_qs.filter(triggered_by=user)

        return jobs_qs.order_by("-created_at")


class Job(models.Model):
    objects = JobQuerySet.as_manager()

    class Type(models.TextChoices):
        PACKAGE = "package", _("Package")
        DELTA_APPLY = "delta_apply", _("Delta Apply")
        PROCESS_PROJECTFILE = "process_projectfile", _("Process QGIS Project File")
        CREATE_PROJECT = "create_project", _("Create Project")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        QUEUED = "queued", _("Queued")
        STARTED = "started", _("Started")
        FINISHED = "finished", _("Finished")
        STOPPED = "stopped", _("Stopped")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    project_id: uuid.UUID
    project = models.ForeignKey(
        "project.Project",
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    output = models.TextField(null=True)
    feedback = JSONField(null=True)

    triggered_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="triggered_jobs",
        limit_choices_to=models.Q(type=User.Type.PERSON),
    )

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

    @property
    def qgis_version(self) -> str | None:
        """Returns QGIS app version used for the job.

        The QGIS version is the one coming from the instanciated worker QGIS app.
        The version number would be in `Major.Minor.Patch-NAME` format, e.g. 3.40.2-Bratislava

        Returns:
            QGIS version if found else None.
        """
        if not self.feedback:
            return None

        feedback_step_data = self.get_feedback_step_data("start_qgis_app")

        if not feedback_step_data:
            return None

        if "qgis_version" in feedback_step_data["returns"]:
            qgis_version = feedback_step_data["returns"]["qgis_version"]
            return qgis_version

        return None

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

        if not self.triggered_by_id and self.created_by_id:
            self.triggered_by = self.created_by

        return super().save(*args, **kwargs)

    def get_feedback_step_data(self, step_name: str) -> dict[str, Any] | None:
        """Extract a step data of a job's feedback.

        Args:
            step_name: name of the step to extract data from.

        Returns:
            data as dict if the step has been found, else None.
        """
        if isinstance(self.feedback, dict):
            steps: list[dict[str, Any]] = self.feedback.get("steps", [])

            for step in steps:
                if step["id"] == step_name:
                    return step

        return None


class PackageJobQuerySet(JobQuerySet):
    pass


class PackageJob(Job):
    objects = PackageJobQuerySet.as_manager()

    def save(self, *args, **kwargs):
        self.type = self.Type.PACKAGE
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Job: package"
        verbose_name_plural = "Jobs: package"


class ProcessProjectfileJobQuerySet(JobQuerySet):
    pass


class ProcessProjectfileJob(Job):
    objects = ProcessProjectfileJobQuerySet.as_manager()

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


class ApplyJobQuerySet(JobQuerySet):
    pass


class ApplyJob(Job):
    objects = ApplyJobQuerySet.as_manager()

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
    apply_job_id: uuid.UUID
    delta_id: uuid.UUID

    apply_job = models.ForeignKey(ApplyJob, on_delete=models.CASCADE)
    delta = models.ForeignKey(Delta, on_delete=models.CASCADE)
    status = models.CharField(
        choices=Delta.Status.choices, default=Delta.Status.PENDING, max_length=32
    )
    feedback = JSONField(null=True)
    modified_pk = models.TextField(null=True)

    def __str__(self):
        return f"{self.apply_job_id}:{self.delta_id}"


class SecretQueryset(models.QuerySet):
    def for_user_and_project(self, user: User, project: Project) -> SecretQueryset:
        """Returns a queryset with secrets for a specific user and project.

        NOTE Do not set `order_by` at the queryset.

        Args:
            user: the user which needs the secrets
            project: the project which the user needs the secrets for

        Returns:
            a Secret queryset of all organization, project and assigned secrets for the given user.

        Raises:
            UserProjectRoleError: if the user is not having any role on the searched project
            UserOrganizationRoleError: if the user is not having any role on the organization that owns the project
        """
        # ensure the user type is a person
        assert user.type == User.Type.PERSON, (
            f"Expected the passed user to be of type PERSON, but got {user.type}!"
        )

        from qfieldcloud.core.permissions_utils import (
            check_user_has_project_roles,
            user_has_organization_roles,
        )

        # ensure the user has access to the organization if private project
        if project.owner.is_organization:
            organization = Organization.objects.get(id=project.owner_id)
            # NOTE While this assertion is nice to have, it causes huge performance penalty on production, so we explicitly check if we are in non-production mode
            if not project.is_public:
                if settings.ENVIRONMENT != "production":
                    # NOTE if the project is public, then it is not necessary for the user to be a member of the project's organization
                    assert user_has_organization_roles(
                        user,
                        organization,
                        OrganizationMember.ALL_ROLES,
                    )
        else:
            organization = None

        # NOTE While this assertion is nice to have, it causes huge performance penalty on production, so we explicitly check if we are in non-production mode
        if settings.ENVIRONMENT != "production":
            assert check_user_has_project_roles(
                user, project, ProjectCollaborator.ALL_ROLES
            )

        # filter only the possible secrets combinations.
        secrets_qs = self.filter(
            Q(
                # organization-assigned secrets
                Q(organization=organization)
                & Q(project__isnull=True)
                & Q(assigned_to__isnull=True)
            )
            | Q(
                # user-assigned organization secrets
                Q(organization=organization)
                & Q(project__isnull=True)
                & Q(assigned_to=user)
            )
            | Q(
                # project-assigned secrets
                Q(organization__isnull=True)
                & Q(project=project)
                & Q(assigned_to__isnull=True)
            )
            | Q(
                # user assigned project secrets
                Q(organization__isnull=True) & Q(project=project) & Q(assigned_to=user)
            )
        )

        # Sort secrets by priority so the first row is the most prioritized one.
        # Later we call `distinct` which will return only the first row for each name.
        # Using `null_first` for organization ensures they are the least prioritized.
        # We must use the FK field for `organization` and `project` and `assigned_to` suffixed with `_id`,
        # otherwise the ordering from the respective joins models is applied.
        secrets_qs = secrets_qs.order_by(
            models.F("name").asc(nulls_last=True),
            models.F("organization_id").asc(nulls_first=True),
            models.F("project_id").asc(nulls_last=True),
            models.F("assigned_to_id").asc(nulls_last=True),
        )
        secrets_qs = secrets_qs.distinct("name")

        return secrets_qs

    def assigned_for_user(self, user: User) -> models.QuerySet[Secret]:
        """Returns a queryset with secrets assigned to a specific user.

        Args:
            user: the user to which secrets are assigned

        Returns:
            a Secret queryset assigned secrets for the given user.
        """
        # ensure the user type is a person
        assert user.type == User.Type.PERSON, (
            f"Expected the passed user to be of type PERSON, but got {user.type}!"
        )

        secret_qs = self.none()
        for project in Project.objects.for_user(user).all():  # type: ignore[attr-defined]
            secret_qs |= self.for_user_and_project(user, project)

        return secret_qs


class Secret(models.Model):
    class Type(models.TextChoices):
        PGSERVICE = "pgservice", _("pg_service")
        ENVVAR = "envvar", _("Environment Variable")

    objects = SecretQueryset.as_manager()

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
        "project.Project",
        on_delete=models.CASCADE,
        related_name="secrets",
        null=True,
        blank=True,
    )

    # The user the secret belongs to. Allows a user to have custom overrides to project envvars and pgservice.
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="assigned_secrets",
        limit_choices_to=Q(type=User.Type.PERSON),
        null=True,
        blank=True,
    )

    # The organization the secret belongs to. Allows an organization to have custom default project envvars and pgservice.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="secrets",
        limit_choices_to=Q(type=User.Type.ORGANIZATION),
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="created_secrets",
        limit_choices_to=Q(type=User.Type.PERSON),
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # encrypted value of the secret.
    value = EncryptedTextField()

    def clean(self, **kwargs) -> None:
        # for project secrets assigned to a user,
        # ensure the user is a collaborator of the project.
        if self.project and self.assigned_to:
            if self.assigned_to not in Person.objects.for_project(
                project=self.project,
                skip_invalid=True,
            ):
                raise ValidationError(
                    _(
                        "Cannot assign a secret to a user that is not a collaborator of the project."
                    )
                )

        # for organization secrets assigned to a user,
        # ensure the user is a member of the organization.
        if self.organization and self.assigned_to:
            if self.assigned_to not in Person.objects.for_organization(
                organization=self.organization
            ):
                raise ValidationError(
                    _(
                        "Cannot assign a secret to a user that is not a member of the organization."
                    )
                )

        return super().clean(**kwargs)

    class Meta:
        ordering = ["project", "assigned_to", "organization"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "type", "name", "assigned_to"],
                name="secret_project_type_name_assigned_to_uniq",
                nulls_distinct=True,
            ),
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "type",
                    "name",
                    "assigned_to",
                ],
                name="secret_organization_type_name_assigned_to_uniq",
                nulls_distinct=True,
            ),
            models.CheckConstraint(
                # we want either the project to be set or the organization, but never both set or unset, therefore ^ (XOR)
                condition=Q(project__isnull=True) ^ Q(organization__isnull=True),
                name="secret_assigned_to_organization_or_user",
            ),
        ]


def get_faulty_deltafile_upload_to(
    instance: models.Model,
    filename: str,
) -> str:
    instance = cast(FaultyDeltaFile, instance)
    key = f"{datetime.now().isoformat()}-{filename}"
    return f"projects/{instance.project.id}/deltafiles/{key}"


class FaultyDeltaFile(models.Model):
    class Meta:
        verbose_name = "Faulty deltafile"

    # The deltafile id if parseable UUID value
    deltafile_id = models.UUIDField(_("Deltafile ID"), editable=False, null=True)

    # The deltafile contents as submitted from the client. It might contain non-valid JSON.
    deltafile = DynamicStorageFileField(
        _("Deltafile"),
        upload_to=get_faulty_deltafile_upload_to,
        # the s3 storage has 1024 bytes (not chars!) limit: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
        max_length=1024,
        null=False,
        blank=False,
    )

    # Time when processing the deltafile failed and the faulty deltafile was created
    created_at = models.DateTimeField(auto_now_add=True)

    # Project that the faulty deltafile was attempted to be uploaded to
    project = models.ForeignKey(
        "project.Project",
        on_delete=models.SET_NULL,
        related_name="faulty_deltafiles",
        null=True,
    )

    # User agent of the client that attempted to upload the faulty deltafile
    user_agent = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    # Traceback of the exception that occurred while processing the deltafile
    traceback = models.TextField(
        blank=True,
        null=True,
    )

    def _get_file_storage_name(self) -> str:
        # Use same storage as project
        return self.project.file_storage
