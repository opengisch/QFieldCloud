from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext as _


class Plan(models.Model):

    # NOTE the values for USER and ORGANIZATION should match the values of TYPE_USER and TYPE_ORGANIZATION in qfieldcloud.core.models.User
    class UserType(models.IntegerChoices):
        USER = (1, _("User"))
        ORGANIZATION = (2, _("Organization"))

    @classmethod
    def get_or_create_default(cls) -> "Plan":
        """Returns the default account type, creating one if none exists.
        To be used as a default value for UserAccount.type"""
        if cls.objects.count() == 0:
            with transaction.atomic():
                cls.objects.create(
                    code="default_user",
                    display_name="default user (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=Plan.UserType.USER,
                )
                cls.objects.create(
                    code="default_org",
                    display_name="default organization (autocreated)",
                    is_default=True,
                    is_public=False,
                    user_type=Plan.UserType.ORGANIZATION,
                )
        return cls.objects.order_by("-is_default").first()

    # unique identifier of the subscription plan
    code = models.CharField(max_length=30, unique=True)

    # the plan would be applicable only to user of that `user_type`
    user_type = models.PositiveSmallIntegerField(
        choices=UserType.choices, default=UserType.USER
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
    has_priority_support = models.BooleanField(default=False)
    can_configure_repackaging_cache_expire = models.BooleanField(default=False)
    min_repackaging_cache_expire = models.DurationField(
        default=timedelta(minutes=60),
        validators=[MinValueValidator(timedelta(minutes=1))],
    )
    synchronizations_per_months = models.PositiveIntegerField(default=30)

    # the account type is visible option for non-admin users
    is_public = models.BooleanField(default=False)

    # the account type is set by default for new users
    is_default = models.BooleanField(default=False)

    # if the organization subscription is changed from unlimited to limited organization members,
    # the existing members that are over the max_organization_members configuration remain active.
    max_organization_members = models.PositiveIntegerField(
        default=0,
        help_text=_(
            "Maximum organization members allowed for particular subscription plan. Set 0 to allow unlimited organization members."
        ),
    )

    def save(self, *args, **kwargs):
        # If default is set to true, we unset default on all other account types
        with transaction.atomic():
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


class ExtraPackageType(models.Model):
    code = models.CharField(max_length=30, unique=True)
    # TODO: decide how to localize display_name. Possible approaches:
    # - django-vinaigrette (never tried, but like the name, and seems to to exactly what we want)
    # - django-modeltranslation (tried, works well, but maybe overkill as it creates new database columns for each locale)
    # - something else ? there's probably some json based stuff
    display_name = models.CharField(max_length=100)
    is_public = models.BooleanField(default=False)


class ExtraPackageTypeStorage(ExtraPackageType):
    megabytes = models.PositiveIntegerField()


class ExtraPackageTypeJobMinutes(ExtraPackageType):
    minutes = models.PositiveIntegerField()


class ExtraPackage(models.Model):
    account = models.ForeignKey(
        "core.UserAccount",
        on_delete=models.CASCADE,
        related_name="extra_packages",
    )
    type = models.ForeignKey(ExtraPackageType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
