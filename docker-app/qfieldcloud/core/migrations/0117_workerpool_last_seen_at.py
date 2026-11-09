from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0116_job_secrets_fetched_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="workerpool",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
