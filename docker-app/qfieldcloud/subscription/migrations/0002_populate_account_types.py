from datetime import timedelta

from django.core.management.color import no_style
from django.db import connection, migrations


def populate_account_types(apps, schema_editor):
    AccountType = apps.get_model("subscription", "AccountType")

    # TODO: match requirements in QF-234
    AccountType.objects.create(
        id=1,  # DO NOT CHANGE! Must match legacy UserAccount.TYPE_COMMUNITY
        code="community",
        display_name="community",
        storage_mb=100,
        storage_keep_versions=3,
        job_minutes=30,
        can_add_storage=False,
        can_add_job_minutes=False,
        is_external_db_supported=False,
        has_priority_support=False,
        can_configure_repackaging_cache_expire=False,
        min_repackaging_cache_expire=timedelta(minutes=60),
        synchronizations_per_months=30,
        is_public=True,
        is_default=True,
    )

    # TODO: match requirements in QF-234
    AccountType.objects.create(
        id=2,  # DO NOT CHANGE! Must match legacy UserAccount.TYPE_PRO
        code="pro",
        display_name="pro",
        storage_mb=1000,
        storage_keep_versions=10,
        job_minutes=100,
        can_add_storage=False,
        can_add_job_minutes=False,
        is_external_db_supported=False,
        has_priority_support=False,
        can_configure_repackaging_cache_expire=True,
        min_repackaging_cache_expire=timedelta(minutes=1),
        synchronizations_per_months=30,
        is_public=True,
        is_default=False,
    )

    # TODO: match requirements in QF-234
    AccountType.objects.create(
        id=3,
        code="organization",
        display_name="organization",
        storage_mb=100,  # we probably mean 1000 ?
        storage_keep_versions=10,
        job_minutes=100,  # TODO: QF-234 says per should be per user !
        can_add_storage=False,
        can_add_job_minutes=False,
        is_external_db_supported=False,
        has_priority_support=False,
        can_configure_repackaging_cache_expire=True,
        min_repackaging_cache_expire=timedelta(minutes=1),
        synchronizations_per_months=30,
        is_public=True,
        is_default=False,
    )

    # Reset the Postgres sequences due to hardcoded ids
    sequence_sql = connection.ops.sequence_reset_sql(no_style(), [AccountType])
    with connection.cursor() as cursor:
        for sql in sequence_sql:
            cursor.execute(sql)

    ExtraPackageTypeStorage = apps.get_model("subscription", "ExtraPackageTypeStorage")
    ExtraPackageTypeStorage.objects.create(
        code="storage_basic",
        display_name="storage_basic",
        megabytes=100,
    )
    ExtraPackageTypeStorage.objects.create(
        code="storage_large",
        display_name="storage_large",
        megabytes=1000,
    )

    ExtraPackageTypeJobMinutes = apps.get_model(
        "subscription", "ExtraPackageTypeJobMinutes"
    )
    ExtraPackageTypeJobMinutes.objects.create(
        code="minutes_basic",
        display_name="minutes_basic",
        minutes=30,
    )
    ExtraPackageTypeJobMinutes.objects.create(
        code="minutes_large",
        display_name="minutes_large",
        minutes=600,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("subscription", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_account_types),
    ]
