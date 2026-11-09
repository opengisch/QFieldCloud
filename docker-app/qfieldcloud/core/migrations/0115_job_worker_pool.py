import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0114_workerpool"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="worker_pool",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="jobs",
                to="core.workerpool",
            ),
        ),
    ]
