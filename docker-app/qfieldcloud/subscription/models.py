from datetime import timedelta
from functools import lru_cache

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext as _
from model_utils.managers import InheritanceManagerMixin
from qfieldcloud.core.models import User


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

    @classmethod
    @lru_cache
    def get_storage_package_type(cls):
        return PackageType.objects.get(type=PackageType.Type.Package)


class Package(models.Model):
    account = models.ForeignKey(
        "core.UserAccount",
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
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
