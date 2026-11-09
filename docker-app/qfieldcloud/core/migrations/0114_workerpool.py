import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0113_alter_delta_created_by_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerPool",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("public_key", models.TextField(blank=True)),
                (
                    "credential_hash",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=64,
                        null=True,
                        unique=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.OneToOneField(
                        blank=True,
                        limit_choices_to=models.Q(("type", 2)),
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="worker_pool",
                        to="core.organization",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("organization__isnull", True)),
                        fields=("organization",),
                        name="workerpool_single_global_pool_uniq",
                        nulls_distinct=False,
                    ),
                ],
            },
        ),
    ]
