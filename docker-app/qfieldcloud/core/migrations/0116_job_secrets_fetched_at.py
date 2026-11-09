from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0115_job_worker_pool"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="secrets_fetched_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
