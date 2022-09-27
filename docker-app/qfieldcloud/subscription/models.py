import logging
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, TypedDict

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from model_utils.managers import InheritanceManagerMixin
from qfieldcloud.core.models import User, UserAccount

from .exceptions import NotPremiumPlanException


class Plan(models.Model):
    @classmethod
    def get_or_create_default(cls) -> "Plan":
        """Returns the default plan, creating one if none exists.
        To be used as a default value for UserAccount.type"""
        if cls.objects.count() == 0:
            with transaction.atomic():
                cls.objects.create(
                    code="default_user",
                    display_name="default user (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=User.Type.PERSON,
                )
                cls.objects.create(
                    code="default_org",
                    display_name="default organization (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=User.Type.ORGANIZATION,
                )
        return cls.objects.order_by("-is_default").first()

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

    # created at
    created_at = models.DateTimeField(auto_now_add=True)

    # updated at
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.user_type not in (User.Type.PERSON, User.Type.ORGANIZATION):
            raise ValidationError(
                'Only "PERSON" and "ORGANIZATION" user types are allowed.'
            )

        with transaction.atomic():
            # If default is set to true, we unset default on all other plans
            if self.is_default:
                Plan.objects.filter(user_type=self.user_type).update(is_default=False)
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

    @classmethod
    @lru_cache
    def get_storage_package_type(cls):
        try:
            return PackageType.objects.get(type=PackageType.Type.STORAGE)
        except PackageType.DoesNotExist:
            return PackageType.objects.create(
                code="storage_package",
                type=PackageType.Type.STORAGE,
                unit_amount=1000,
                unit_label="MB",
                min_quantity=0,
                max_quantity=100,
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


# TODO add check constraint makes sure there are no two active additional packages at the same time,
# because we assume that once you change your quantity, the old Package instance has an end_date
# and a new one with the new quantity is created right away.


class SubscriptionQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        qs = self.filter(
            Q(active_since__lte=now)
            & (Q(active_until__isnull=True) | Q(active_until__gte=now))
        )

        return qs


class Subscription(models.Model):

    objects = SubscriptionQuerySet.as_manager()

    class Status(models.TextChoices):
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
        INACTIVE_REQUESTED_CREATE = "inactive Requested_create", _(
            "Inactive_Requested Create"
        )
        # requested creating the subscription on Stripe
        INACTIVE_AWAITS_PAYMENT = "inactive_awaits_payment", _(
            "Inactive Awaits Payment"
        )
        # payment succeeded
        ACTIVE_PAID = "active_paid", _("Active Paid")
        # payment failed, but the subscription is still active
        ACTIVE_PAST_DUE = "active_past_due", _("Active Past Due")
        # successfully cancelled
        INACTIVE_CANCELLED = "inactive_cancelled", _("Inactive Cancelled")

    class UpdateSubscriptionKwargs(TypedDict):
        status: "Subscription.Status"
        active_since: datetime
        active_until: Optional[datetime]
        requested_cancel_at: Optional[datetime]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)

    plan = models.ForeignKey(
        Plan,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

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
    # NOTE this field remains currently unused.
    current_period_since = models.DateTimeField(null=True, blank=True)

    # the timestamp when the current billing period ends
    # NOTE ignored for subscription validity checks, but used to calculate the activation date when additional packages change
    current_period_until = models.DateTimeField(null=True, blank=True)

    @property
    def active_storage_total_mb(self) -> int:
        return self.plan.storage_mb + self.active_storage_package_mb

    @property
    def active_storage_package(self) -> Package:
        return self.get_active_package(PackageType.get_storage_package_type())

    @property
    def active_storage_package_quantity(self) -> int:
        return self.get_active_package_quantity(PackageType.get_storage_package_type())

    @property
    def active_storage_package_mb(self) -> int:
        return (
            self.get_active_package_quantity(PackageType.get_storage_package_type())
            * PackageType.get_storage_package_type().unit_amount
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
    def future_storage_package_changed_mb(self) -> int:
        if self.future_storage_package or (
            self.active_storage_package and self.active_storage_package.active_until
        ):
            return self.future_storage_package_mb - self.active_storage_package_mb
        else:
            return 0

    def get_active_package(self, package_type: PackageType) -> Package:
        storage_package_qs = self.packages.active().filter(type=package_type)

        return storage_package_qs.first()

    def get_active_package_quantity(self, package_type: PackageType) -> int:
        package = self.get_active_package(package_type)
        return package.quantity if package else 0

    def get_future_package(self, package_type: PackageType) -> Package:
        storage_package_qs = self.packages.future().filter(type=package_type)

        return storage_package_qs.first()

    def get_future_package_quantity(self, package_type: PackageType) -> int:
        package = self.get_future_package(package_type)
        return package.quantity if package else 0

    def set_package_quantity(
        self,
        package_type: PackageType,
        quantity: int,
        active_since: datetime = None,
    ):
        if not self.plan.is_premium:
            raise NotPremiumPlanException(
                "Only premium accounts can have additional packages!"
            )

        with transaction.atomic():
            if active_since is None:
                active_since = timezone.now()
            new_package = None

            # delete future packages for that subscription, as we would create a new one if needed
            # NOTE first delete the future package and then create the new one,
            # otherwise the active period overlap constraint will complain
            Package.objects.future().filter(
                subscription=self,
                type=package_type,
            ).delete()

            try:
                old_package = (
                    Package.objects.active()
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
    def get_or_create_active_subscription(cls, account: UserAccount) -> "Subscription":
        """Returns the currently active subscription, if not exists returns a newly created subscription with the default plan.

        Args:
            account (UserAccount): the account the subscription belongs to.

        Returns:
            Subscription: the currently active subscription
        """
        try:
            subscription = cls.objects.active().get(account_id=account.pk)
        except cls.DoesNotExist:
            subscription = cls.create_default_plan_subscription(account)

        return subscription

    @classmethod
    def update_subscription(
        cls,
        subscription: "Subscription",
        **kwargs: UpdateSubscriptionKwargs,
    ) -> "Subscription":
        """Updates the subscription properties.

        Args:
            subscription (Subscription): subscription to be updated

        Returns:
            Subscription: the same as the subscription argument
        """
        if not kwargs:
            return subscription

        with transaction.atomic():
            cls.objects.select_for_update().get(id=subscription.id)
            update_fields = []

            for attr_name, attr_value in kwargs.items():
                update_fields.append(attr_name)
                setattr(subscription, attr_name, attr_value)

            logging.info(f"Updated subscription's fields: {', '.join(update_fields)}")

            subscription.save(update_fields=update_fields)

        return subscription

    @classmethod
    def create_default_plan_subscription(
        cls, account: UserAccount, active_since: datetime = None
    ) -> "Subscription":
        """Activates the default (free) subscription for a given account.

        Args:
            account (UserAccount): the account the subscription belongs to.
            active_since (datetime): active since for the subscription

        Returns:
            Subscription: the currently active subscription.
        """
        if active_since is None:
            active_since = timezone.now()

        plan = Plan.objects.get(
            user_type=account.user.type,
            is_default=True,
        )

        subscription = cls.objects.create(
            plan=plan,
            account=account,
            created_by=account.user,
            status=cls.Status.ACTIVE_PAID,
            active_since=active_since,
        )

        return subscription
