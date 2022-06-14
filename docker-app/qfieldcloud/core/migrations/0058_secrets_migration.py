import os

import django_cryptography.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    def rotate_secret_from_old_to_new(apps, schema_editor):
        Secret = apps.get_model("core", "Secret")

        for secret in Secret.objects.all():
            secret.value = secret.old_value
            secret.save()

    dependencies = [
        ("core", "0057_auto_20220701_2140"),
    ]

    operations = [
        migrations.RenameField(
            model_name="secret",
            old_name="value",
            new_name="old_value",
        ),
        migrations.AddField(
            model_name="secret",
            name="value",
            field=django_cryptography.fields.encrypt(
                models.TextField(null=True),
                key=os.environ.get("CRYPTOGRAPHY_KEY_20220612").encode(),
            ),
        ),
        migrations.RunPython(
            rotate_secret_from_old_to_new,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="secret",
            name="old_value",
        ),
    ]
