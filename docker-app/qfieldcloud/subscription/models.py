import logging
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Type, TypedDict, cast

from constance import config
from deprecated import deprecated
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Case, Q, QuerySet, When
from django.db.models import Value as V
from django.utils import timezone
from django.utils.translation import gettext as _
from model_utils.managers import InheritanceManagerMixin

from qfieldcloud.core.models import Organization, Person, User, UserAccount

from .exceptions import NotPremiumPlanException

logger = logging.getLogger(__name__)


def get_subscription_model() -> "Subscription":
    model = apps.get_model(settings.QFIELDCLOUD_SUBSCRIPTION_MODEL)
    return cast(Subscription, model)


class SubscriptionStatus(models.TextChoices):
    """Status of the subscription.

    Initially the status is INACTIVE_DRAFT.

    INACTIVE_DRAFT -> (INACTIVE_DRAFT_EXPIRED, INACTIVE_REQUESTED_CREATE)
    INACTIVE_REQUESTED_CREATE -> (INACTIVE_AWAITS_PAYMENT, INACTIVE_CANCELLED)

    """

    # the user drafted a subscription, initial status
    INACTIVE_DRAFT = "inactive_draft", _("Inactive Draft")
    # the user draft expired (e.g. a new subscription is attempted)
    INACTIVE_DRAFT_EXPIRED = "inactive_draft_expired", _("Inactive Draft Expired")
    # requested creating the subscription on Stripe
    INACTIVE_REQUESTED_CREATE = (
        "inactive_requested_create",
        _("Inactive Requested Create"),
    )
    # requested creating the subscription on Stripe
    INACTIVE_AWAITS_PAYMENT = "inactive_awaits_payment", _("Inactive Awaits Payment")
    # payment succeeded
    ACTIVE_PAID = "active_paid", _("Active Paid")
    # payment failed, but the subscription is still active
    ACTIVE_PAST_DUE = "active_past_due", _("Active Past Due")
    # successfully cancelled
    INACTIVE_CANCELLED = "inactive_cancelled", _("Inactive Cancelled")


class Plan(models.Model):
    @classmethod
    def get_or_create_default(cls) -> "Plan":
        """Returns the default plan, creating one if none exists.
        To be used as a default value for UserAccount.type"""
        if not cls.objects.exists():
            with transaction.atomic():
                cls.objects.create(
                    code="default_user",
                    display_name="default user (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=User.Type.PERSON,
                    initial_subscription_status=SubscriptionStatus.ACTIVE_PAID,
                )
                cls.objects.create(
                    code="default_org",
                    display_name="default organization (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=User.Type.ORGANIZATION,
                    initial_subscription_status=SubscriptionStatus.ACTIVE_PAID,
                )

        result = cls.objects.order_by("-is_default").first()

        return cast(Plan, result)

    @classmethod
    def get_plans_for_user(cls, user: User, user_type: User.Type) -> QuerySet["Plan"]:
        """
        Return all public plans of the given `user_type`, filtering out
        trial plans for organizations when no trials remain.
        """
        filters = {
            "is_public": True,
            "user_type": user_type,
        }

        if (
            user_type == User.Type.ORGANIZATION
            and user.remaining_trial_organizations == 0
        ):
            filters["is_trial"] = False

        return cls.objects.filter(**filters)

    # unique identifier of the subscription plan
    code = models.CharField(max_length=100, unique=True)

    # the plan would be applicable only to user of that `user_type`
    user_type = models.PositiveSmallIntegerField(
        choices=User.Type.choices, default=User.Type.PERSON
    )

    # relative ordering of the record
    ordering = models.PositiveIntegerField(
        default=0,
        help_text=_(
            'Relative ordering of the record. Lower values have higher priority (will be first in the list). Records with same ordering will be sorted by "Display name" and "Code". Please set with gaps for different records for easy reordering (e.g. 5, 10, 15, but not 5, 6, 7).'
        ),
    )

    # TODO: match requirements in QF-234 (fields like automatic old versions)
    # TODO: decide how to localize display_name. Possible approaches:
    # - django-vinaigrette (never tried, but like the name, and seems to to exactly what we want)
    # - django-modeltranslation (tried, works well, but maybe overkill as it creates new database columns for each locale)
    # - something else ? there's probably some json based stuff
    display_name = models.CharField(max_length=100)
    storage_mb = models.PositiveIntegerField(default=10)
    storage_keep_versions = models.PositiveIntegerField(default=10)
    job_minutes = models.PositiveIntegerField(default=10)
    can_add_storage = models.BooleanField(default=False)
    can_add_job_minutes = models.BooleanField(default=False)
    is_external_db_supported = models.BooleanField(default=False)
    can_configure_repackaging_cache_expire = models.BooleanField(default=False)
    min_repackaging_cache_expire = models.DurationField(
        default=timedelta(minutes=60),
        validators=[MinValueValidator(timedelta(minutes=1))],
    )
    synchronizations_per_months = models.PositiveIntegerField(default=30)

    # the plan is visible option for non-admin users
    is_public = models.BooleanField(default=False)

    # the plan is set by default for new users
    is_default = models.BooleanField(default=False)

    # the plan is marked as premium which assumes it has premium access
    is_premium = models.BooleanField(default=False)

    # the plan is set as trial
    is_trial = models.BooleanField(default=False)

    # the plan is metered or licensed. If it metered, it is automatically post-paid.
    is_metered = models.BooleanField(default=False)

    # the plan is cancellable. If it True, the plan cannot be cancelled.
    is_cancellable = models.BooleanField(default=True)

    # the plan is cancellable. If it True, the plan cannot be cancelled.
    is_storage_modifiable = models.BooleanField(default=True)

    # The maximum number of organizations members that are allowed to be added per organization
    # This constraint is useful for public administrations with limited resources who want to cap
    # the maximum amount of money that they are going to pay.
    # Only makes sense when the user_type == User.Type.ORGANIZATION
    # If the organization subscription is changed from unlimited to limited organization members,
    # the existing members that are over the max_organization_members configuration remain active.
    max_organization_members = models.IntegerField(
        default=-1,
        help_text=_(
            "Maximum organization members allowed. Set -1 to allow unlimited organization members."
        ),
    )

    # The maximum number of premium collaborators that are allowed to be added per project.
    # If the project owner's plan is changed from unlimited to limited organization members,
    # the existing members that are over the `max_premium_collaborators_per_private_project` configuration remain active.
    max_premium_collaborators_per_private_project = models.IntegerField(
        default=-1,
        help_text=_(
            "Maximum premium collaborators per private project. Set -1 to allow unlimited project collaborators."
        ),
    )

    # The maximum number of trial organizations that the user can create.
    # Set -1 to allow unlimited trial organizations.
    max_trial_organizations = models.IntegerField(
        default=1,
        help_text=_(
            "Maximum number of trial organizations that the user can create. Set -1 to allow unlimited trial organizations."
        ),
    )

    # The status when a new subscription is created
    initial_subscription_status = models.CharField(
        max_length=100,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.INACTIVE_DRAFT,
    )

    # comma separated list of plan codes, which given plan can upgrade to.
    upgradable_to = models.CharField(max_length=1000, null=True, blank=True)

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    # admin only notes, not visible to end users
    notes = models.TextField(
        _("Admin notes"),
        blank=True,
        null=True,
        help_text=_(
            "These notes are for internal purposes only and will never be shown to the end users."
        ),
    )

    @property
    def storage_bytes(self) -> int:
        return self.storage_mb * 1000 * 1000

    def save(self, *args, **kwargs):
        if self.user_type not in (User.Type.PERSON, User.Type.ORGANIZATION):
            raise ValidationError(
                'Only "PERSON" and "ORGANIZATION" user types are allowed.'
            )

        with transaction.atomic():
            # If default is set to true, we unset default on all other plans
            if self.is_default:
                Plan.objects.filter(user_type=self.user_type).exclude(
                    pk=self.pk
                ).update(is_default=False)

            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.display_name} ({self.code})"

    class Meta:
        ordering = (
            "ordering",
            "display_name",
            "code",
        )


class PackageTypeManager(InheritanceManagerMixin, models.Manager):
    # NOTE you should never have `select_related("packagetype")` if you want the polymorphism to work.
    def get_queryset(self):
        return super().get_queryset().select_subclasses()


class PackageType(models.Model):
    objects = PackageTypeManager()

    class Type(models.TextChoices):
        STORAGE = "storage", _("Storage")

    code = models.CharField(max_length=100, unique=True)
    # TODO: decide how to localize display_name. Possible approaches:
    # - django-vinaigrette (never tried, but like the name, and seems to to exactly what we want)
    # - django-modeltranslation (tried, works well, but maybe overkill as it creates new database columns for each locale)
    # - something else ? there's probably some json based stuff
    display_name = models.CharField(max_length=100)

    # the type of the package
    type = models.CharField(choices=Type.choices, max_length=100, unique=True)

    # whether the package is available for the general public
    is_public = models.BooleanField(default=False)

    # the minimum quantity per subscription
    min_quantity = models.PositiveIntegerField()

    # the maximum quantity per subscription
    max_quantity = models.PositiveIntegerField()

    # the size of the package in `unit_label` units
    unit_amount = models.PositiveIntegerField()

    # Unit of measurement (e.g. gigabyte, minute, etc)
    unit_label = models.CharField(max_length=100, null=True, blank=True)

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    # admin only notes, not visible to end users
    notes = models.TextField(
        _("Admin notes"),
        blank=True,
        null=True,
        help_text=_(
            "These notes are for internal purposes only and will never be shown to the end users."
        ),
    )

    @classmethod
    @lru_cache
    def get_storage_package_type(cls) -> "PackageType":
        # NOTE if the cache is still returning the old result, please restart the whole `app` container
        try:
            return cls.objects.get(type=cls.Type.STORAGE)
        except cls.DoesNotExist:
            return cls.objects.create(
                code="storage",
                display_name="Additional storage",
                is_public=True,
                type=cls.Type.STORAGE,
                unit_amount=1000,
                unit_label="MB",
                min_quantity=0,
                max_quantity=50,
            )


class PackageQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        qs = self.filter(
            active_since__lte=now, subscription__plan__is_premium=True
        ).filter(Q(active_until__isnull=True) | Q(active_until__gte=now))

        return qs

    def future(self):
        now = timezone.now()
        qs = self.filter(
            active_since__gte=now, subscription__plan__is_premium=True
        ).order_by("active_since")

        return qs


class Package(models.Model):
    objects = PackageQuerySet.as_manager()

    subscription = models.ForeignKey(
        "subscription.Subscription",
        on_delete=models.CASCADE,
        related_name="packages",
    )
    type = models.ForeignKey(
        PackageType, on_delete=models.CASCADE, related_name="packages"
    )
    quantity = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1),
        ],
    )
    active_since = models.DateTimeField()
    active_until = models.DateTimeField(null=True, blank=True)

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    # admin only notes, not visible to end users
    notes = models.TextField(
        _("Admin notes"),
        blank=True,
        null=True,
        help_text=_(
            "These notes are for internal purposes only and will never be shown to the end users."
        ),
    )


# TODO add check constraint makes sure there are no two active additional packages at the same time,
# because we assume that once you change your quantity, the old Package instance has an end_date
# and a new one with the new quantity is created right away.


class SubscriptionQuerySet(models.QuerySet):
    def current(self):
        """
        Returns the subscriptions which are relevant to the current moment.
        NOTE Some of the subscriptions in the queryset might not be active, but cancelled or drafted.
        """
        now = timezone.now()
        qs = self.filter(
            Q(active_since__lte=now)
            & (Q(active_until__isnull=True) | Q(active_until__gte=now))
        ).select_related("plan")

        return qs

    def managed_by(self, user_id: int):
        """Returns all subscriptions that are managed by given `user_id`. It means the owner personal account and all organizations they own.

        Args:
            user_id: the user we are searching against
        """
        if not user_id:
            # NOTE: for logged out AnonymousUser the user_id is None
            return self.none()

        return self.filter(
            Q(account_id=user_id)
            | Q(account__user__organization__organization_owner_id=user_id)
        )

    def activeness(self):
        """Annotates with additional `is_active` boolean field.

        `is_active` - if the period and status are active.

        NOTE This method is intended to be automatically called for each queryset.
        """
        is_period_active_condition = Q(active_since__lte=V("now")) & (
            Q(active_until__isnull=True) | Q(active_until__gte=V("now"))
        )
        is_status_active_condition = Q(
            status__in=(
                Subscription.Status.ACTIVE_PAID,
                Subscription.Status.ACTIVE_PAST_DUE,
            )
        )
        return self.annotate(
            is_active=Case(
                When(
                    is_period_active_condition & is_status_active_condition, then=True
                ),
                default=False,
            ),
        )


class SubscriptionManager(models.Manager):
    def get_queryset(self):
        return SubscriptionQuerySet(self.model, using=self._db).activeness()

    def current(self):
        return self.get_queryset().current()

    def managed_by(self, user_id: int):
        return self.get_queryset().managed_by(user_id)


class AbstractSubscription(models.Model):
    class Meta:
        abstract = True

    objects = SubscriptionManager()

    Status = SubscriptionStatus

    class UpdateSubscriptionKwargs(TypedDict):
        status: "Subscription.Status"  # type: ignore
        active_since: datetime
        active_until: datetime | None
        requested_cancel_at: datetime | None

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)

    plan = models.ForeignKey(
        Plan,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

    is_frontend_user_editable = False

    account = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )

    status = models.CharField(
        max_length=100, choices=Status.choices, default=Status.INACTIVE_DRAFT
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="+",
    )

    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    requested_cancel_at = models.DateTimeField(
        _("Requested cancel at"), null=True, blank=True
    )

    # the time since the subscription is active. Note the value is null until the subscription is valid.
    active_since = models.DateTimeField(_("Active since"), null=True, blank=True)

    active_until = models.DateTimeField(_("Active until"), null=True, blank=True)

    # the timestamp used for time calculations when the billing period starts and ends
    billing_cycle_anchor_at = models.DateTimeField(null=True, blank=True)

    # the timestamp when the current billing period started
    # NOTE ignored when checking if subscription is 'current' (see `active_since and `active_until`).
    # `current_period_since` and `current_period_until` are both either `None` or `datetime`
    current_period_since = models.DateTimeField(null=True, blank=True)

    # the timestamp when the current billing period ends
    # NOTE ignored when checking if subscription is 'current' (see `active_since and `active_until`),
    # but used to calculate the activation date when additional packages change.
    # `current_period_since` and `current_period_until` are both either `None` or `datetime`
    current_period_until = models.DateTimeField(null=True, blank=True)

    # admin only notes, not visible to end users
    notes = models.TextField(
        _("Admin notes"),
        blank=True,
        null=True,
        help_text=_(
            "These notes are for internal purposes only and will never be shown to the end users."
        ),
    )

    @property
    @deprecated("Use `AbstractSubscription.active_storage_total_bytes` instead")
    def active_storage_total_mb(self) -> int:
        return self.plan.storage_mb + self.active_storage_package_mb

    @property
    def active_storage_total_bytes(self) -> int:
        return self.plan.storage_bytes + self.active_storage_package_bytes

    @property
    def active_storage_package(self) -> Package:
        return self.get_active_package(PackageType.get_storage_package_type())

    @property
    def active_storage_package_quantity(self) -> int:
        return self.get_active_package_quantity(PackageType.get_storage_package_type())

    @property
    @deprecated("Use `AbstractSubscription.active_storage_package_bytes` instead")
    def active_storage_package_mb(self) -> int:
        return (
            self.get_active_package_quantity(PackageType.get_storage_package_type())
            * PackageType.get_storage_package_type().unit_amount
        )

    @property
    def active_storage_package_bytes(self) -> int:
        return (
            (
                self.get_active_package_quantity(PackageType.get_storage_package_type())
                * PackageType.get_storage_package_type().unit_amount
            )
            * 1000
            * 1000
        )

    @property
    def future_storage_total_mb(self) -> int:
        return self.plan.storage_mb + self.future_storage_package_mb

    @property
    def future_storage_package(self) -> Package:
        return self.get_future_package(PackageType.get_storage_package_type())

    @property
    def future_storage_package_quantity(self) -> int:
        return self.get_future_package_quantity(PackageType.get_storage_package_type())

    @property
    def future_storage_package_mb(self) -> int:
        return (
            self.get_future_package_quantity(PackageType.get_storage_package_type())
            * PackageType.get_storage_package_type().unit_amount
        )

    @property
    def future_storage_package_changed_quantity(self) -> int:
        if self.future_storage_package or (
            self.active_storage_package and self.active_storage_package.active_until
        ):
            return (
                self.future_storage_package_quantity
                - self.active_storage_package_quantity
            )
        else:
            return 0

    @property
    def future_storage_package_changed_mb(self) -> int:
        return (
            self.future_storage_package_changed_quantity
            * PackageType.get_storage_package_type().unit_amount
        )

    @property
    def has_current_period(self) -> bool:
        return (
            self.current_period_since is not None
            and self.current_period_until is not None
        )

    @property
    def active_users(self):
        "Returns the queryset of active users for running stripe billing period or None."
        if not self.account.user.is_organization:
            return None

        if self.has_current_period:
            return self.account.user.active_users(
                self.current_period_since,
                self.current_period_until,
            )

        return None

    @property
    def active_users_count(self) -> int:
        # if non-organization account, then it is always 1 user
        if not self.account.user.is_organization:
            return 1

        if self.active_users is None:
            return 0

        return self.active_users.count()

    def get_active_package(self, package_type: PackageType) -> Package:
        storage_package_qs = self.packages.active().filter(type=package_type)  # type: ignore

        return storage_package_qs.first()

    def get_active_package_quantity(self, package_type: PackageType) -> int:
        package = self.get_active_package(package_type)
        return package.quantity if package else 0

    def get_future_package(self, package_type: PackageType) -> Package:
        storage_package_qs = self.packages.future().filter(type=package_type)  # type: ignore

        return storage_package_qs.first()

    def get_future_package_quantity(self, package_type: PackageType) -> int:
        package = self.get_future_package(package_type)
        if package:
            return package.quantity
        else:
            package = self.get_active_package(package_type)

            if package and not package.active_until:
                return package.quantity

        return 0

    def set_package_quantity(
        self,
        package_type: PackageType,
        quantity: int,
        active_since: datetime | None = None,
    ):
        if not self.plan.is_premium:
            raise NotPremiumPlanException(
                "Only premium accounts can have additional packages!"
            )

        with transaction.atomic():
            if active_since is None:
                active_since = timezone.now()

            active_since = active_since.replace(microsecond=0)
            new_package = None

            # delete future packages for that subscription, as we would create a new one if needed
            # NOTE first delete the future package and then create the new one,
            # otherwise the active period overlap constraint will complain
            Package.objects.future().filter(  # type: ignore
                subscription=self,
                type=package_type,
            ).delete()

            try:
                old_package = (
                    Package.objects.active()  # type: ignore
                    .select_for_update()
                    .get(
                        subscription=self,
                        type=package_type,
                    )
                )
                old_package.active_until = active_since
                old_package.save(update_fields=["active_until"])
            except Package.DoesNotExist:
                old_package = None

            if quantity > 0:
                new_package = Package.objects.create(
                    subscription=self,
                    quantity=quantity,
                    type=package_type,
                    active_since=active_since,
                )

        return old_package, new_package

    @classmethod
    def get_or_create_current_subscription(cls, account: UserAccount) -> "Subscription":
        """Returns the current subscription, if not exists returns a newly created subscription with the default plan.

        Args:
            account: the account the subscription belongs to.

        Returns:
            the current subscription

        TODO Python 3.11 the actual return type is Self
        """
        try:
            subscription = cls.objects.current().get(account_id=account.pk)  # type: ignore
        except cls.DoesNotExist:
            subscription = cls.create_default_plan_subscription(account)

        return cast(Subscription, subscription)

    @classmethod
    def get_upcoming_subscription(cls, account: UserAccount) -> "Subscription":
        result = (
            cls.objects.filter(account_id=account.pk, active_since__gt=timezone.now())
            .exclude(status__in=[Subscription.Status.INACTIVE_CANCELLED])
            .order_by("active_since")
            .first()
        )
        return cast(Subscription, result)

    @classmethod
    def update_subscription(
        cls,
        subscription: "Subscription",
        **kwargs: UpdateSubscriptionKwargs,
    ) -> "Subscription":
        """Updates the subscription properties.

        Args:
            subscription: subscription to be updated

        Returns:
            the same as the subscription argument

        TODO Python 3.11 the actual return type is Self
        """
        if not kwargs:
            return subscription

        with transaction.atomic():
            cls.objects.select_for_update().get(id=subscription.id)  # type: ignore
            update_fields = []

            if (
                subscription.active_since is None
                and kwargs.get("active_since") is not None
            ):
                cls.objects.current().filter(
                    account=subscription.account,
                ).exclude(  # type: ignore
                    pk=subscription.pk,
                ).update(
                    status=Subscription.Status.INACTIVE_CANCELLED,
                    active_until=kwargs["active_since"],
                )

            for attr_name, attr_value in kwargs.items():
                update_fields.append(attr_name)
                setattr(subscription, attr_name, attr_value)

            logger.info(f"Updated subscription's fields: {', '.join(update_fields)}")

            subscription.save(update_fields=update_fields)

        return subscription

    @classmethod
    def create_default_plan_subscription(
        cls, account: UserAccount, active_since: datetime | None = None
    ) -> "AbstractSubscription":
        """Creates the default subscription for a given account.

        Args:
            account: the account the subscription belongs to.
            active_since: active since for the subscription

        Returns:
            the created subscription.

        TODO Python 3.11 the actual return type is Self
        """
        plan = Plan.objects.get(
            user_type=account.user.type,
            is_default=True,
        )

        if account.user.is_organization:
            # NOTE sometimes `account.user` is not an organization, e.g. when setting
            # `active_until` on an organization account
            created_by = Organization.objects.get(pk=account.pk).organization_owner
        else:
            created_by = account.user

        if not isinstance(created_by, Person):
            created_by = Person.objects.get(pk=created_by.pk)

        if active_since is None:
            active_since = timezone.now()

        _trial_subscription, regular_subscription = cls.create_subscription(
            account=account,
            plan=plan,
            created_by=created_by,
            active_since=active_since,
        )

        return regular_subscription

    @classmethod
    def create_subscription(
        cls,
        account: UserAccount,
        plan: Plan,
        created_by: Person,
        active_since: datetime | None = None,
    ) -> tuple[Type["AbstractSubscription"] | None, "AbstractSubscription"]:
        """Creates a subscription for a given account to a given plan. If the plan is a trial, create the default subscription in the end of the period.

        Args:
            account: the account the subscription belongs to.
            plan: the plan to subscribe to. Note if the the plan is a trial, the first return value would be the trial subscription, otherwise it would be None.
            created_by: created by.
            active_since: active since for the subscription.

        Returns:
            the created trial subscription if the given plan was a trial and the regular subscription.

        TODO Python 3.11 the actual return type is Self
        """
        if active_since:
            # remove microseconds as there will be slight shift with the remote system data
            active_since = active_since.replace(microsecond=0)

        regular_active_since: datetime | None = None
        if plan.is_trial:
            assert isinstance(active_since, datetime), (
                "Creating a trial plan requires `active_since` to be a valid datetime object"
            )

            active_until = active_since + timedelta(days=config.TRIAL_PERIOD_DAYS)
            logger.info(
                f"Creating trial subscription from {active_since=} to {active_until=}"
            )
            trial_subscription = cls.objects.create(
                plan=plan,
                account=account,
                created_by=created_by,
                status=plan.initial_subscription_status,
                active_since=active_since,
                active_until=active_until,
            )
            # NOTE to get annotations, mostly `is_active`
            trial_subscription_obj = cls.objects.get(pk=trial_subscription.pk)

            if (
                account.user.is_organization
                and account.user.organization_owner.remaining_trial_organizations > 0
            ):
                account.user.organization_owner.remaining_trial_organizations -= 1
                account.user.organization_owner.save(
                    update_fields=["remaining_trial_organizations"]
                )

            # the trial plan should be the default plan
            regular_plan = Plan.objects.get(
                user_type=account.user.type,
                is_default=True,
            )

            # the end date of the trial is the start date of the regular
            regular_active_since = active_until
        else:
            trial_subscription_obj = None
            regular_plan = plan
            regular_active_since = active_since

            # NOTE in case the user had a custom amount set (e.g manually set by support) this will
            # be overwritten by a subscription plan change.
            # But taking care of this would add quite some complexity.
            if account.user.is_person:
                account.user.remaining_trial_organizations = (
                    regular_plan.max_trial_organizations
                )
                account.user.save(update_fields=["remaining_trial_organizations"])

        logger.info(f"Creating regular subscription from {regular_active_since}")
        regular_subscription = cls.objects.create(
            plan=regular_plan,
            account=account,
            created_by=created_by,
            status=regular_plan.initial_subscription_status,
            active_since=regular_active_since,
        )
        # NOTE to get annotations, mostly `is_active`
        regular_subscription_obj = cls.objects.get(pk=regular_subscription.pk)

        return trial_subscription_obj, regular_subscription_obj

    def clean(self):
        """
        Validates that the subscription's active period does not overlap with
        any other active subscriptions for the same account.
        """
        # If there is no `active_since`, nothing to check.
        if not self.active_since:
            return

        conflicting_subscriptions_qs = (
            self.__class__.objects.filter(
                account=self.account,
            )
            .exclude(pk=self.pk)
            .filter(
                Q(active_since__lt=self.active_since)
                & (Q(active_until__isnull=True) | Q(active_until__gt=self.active_since))
            )
        )

        if conflicting_subscriptions_qs.exists():
            raise ValidationError(
                {
                    "active_since": _(
                        "This account already has an active subscription that overlaps with this period. Please cancel the existing subscription or choose a different time range."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        active_storage_total_mb = (
            self.active_storage_package_mb if hasattr(self, "packages") else 0
        )
        return f"{self.__class__.__name__} #{self.id} user:{self.account.user.username} plan:{self.plan.code} total:{active_storage_total_mb}MB"


class Subscription(AbstractSubscription):
    pass


class CurrentSubscription(AbstractSubscription):
    class Meta:
        managed = False
        db_table = "current_subscriptions_vw"

    account = models.OneToOneField(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="current_subscription_vw",
    )
