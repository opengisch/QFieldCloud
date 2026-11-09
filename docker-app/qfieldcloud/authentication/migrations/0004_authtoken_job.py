import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0003_authtoken_authenticat_created_ee68f9_idx"),
        ("core", "0113_alter_delta_created_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="authtoken",
            name="job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="core.job",
                verbose_name="Job",
            ),
        ),
    ]
