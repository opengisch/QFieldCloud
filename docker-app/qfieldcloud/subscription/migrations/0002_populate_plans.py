from datetime import timedelta

from django.core.management.color import no_style
from django.db import connection, migrations


def populate_plans(apps, schema_editor):
    Plan = apps.get_model("subscription", "Plan")

    if not Plan.objects.filter(code="community").count():
        Plan.objects.create(
            id=1,  # DO NOT CHANGE! Must match legacy UserAccount.TYPE_COMMUNITY
            code="community",
            user_type=1,
            ordering=1100,
            display_name="community",
            storage_mb=10000,
            storage_keep_versions=10,
            job_minutes=10000,
            can_add_storage=False,
            can_add_job_minutes=False,
            is_external_db_supported=False,
            can_configure_repackaging_cache_expire=False,
            min_repackaging_cache_expire=timedelta(minutes=60),
            synchronizations_per_months=30,
            max_organization_members=-1,
            is_public=True,
            is_default=True,
        )

    if not Plan.objects.filter(code="organization").count():
        Plan.objects.create(
            id=2,
            code="organization",
            user_type=2,
            ordering=5100,
            display_name="organization",
            storage_mb=5000,
            storage_keep_versions=10,
            job_minutes=100,  # TODO: QF-234 says per should be per user !
            can_add_storage=False,
            can_add_job_minutes=False,
            is_external_db_supported=True,
            can_configure_repackaging_cache_expire=True,
            min_repackaging_cache_expire=timedelta(minutes=1),
            synchronizations_per_months=30,
            max_organization_members=-1,
            is_public=True,
            is_default=True,
        )

    # Reset the Postgres sequences due to hardcoded ids
    sequence_sql = connection.ops.sequence_reset_sql(no_style(), [Plan])
    with connection.cursor() as cursor:
        for sql in sequence_sql:
            cursor.execute(sql)

    ExtraPackageTypeStorage = apps.get_model("subscription", "ExtraPackageTypeStorage")

    if not ExtraPackageTypeStorage.objects.filter(code="storage_medium").count():
        ExtraPackageTypeStorage.objects.create(
            code="storage_medium",
            display_name="Medium +1000MB",
            is_public=True,
            megabytes=1000,
        )

    ExtraPackageTypeJobMinutes = apps.get_model(
        "subscription", "ExtraPackageTypeJobMinutes"
    )
    if not ExtraPackageTypeJobMinutes.objects.filter(code="minutes_medium").count():
        ExtraPackageTypeJobMinutes.objects.create(
            code="minutes_medium",
            display_name="minutes_medium",
            is_public=True,
            minutes=30,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("subscription", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_plans, migrations.RunPython.noop),
    ]
