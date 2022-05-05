from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models


class AccountType(models.Model):
    @classmethod
    def get_or_create_default(cls) -> "AccountType":
        """Returns the default account type, creating one if none exists.
        To be used as a default value for UserAccount.type"""
        if cls.objects.count() == 0:
            cls.objects.create(
                code="default",
                display_name="default (autocreated)",
                is_default=True,
                is_public=False,
            )
        return cls.objects.order_by("-is_default").first()

    code = models.CharField(max_length=30, unique=True)
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
    is_public = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # If default is set to true, we unset default on all other account types
        if self.is_default:
            AccountType.objects.update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.display_name} ({self.code})"


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
