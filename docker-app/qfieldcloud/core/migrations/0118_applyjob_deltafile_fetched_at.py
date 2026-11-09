from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0117_workerpool_last_seen_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="applyjob",
            name="deltafile_fetched_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
