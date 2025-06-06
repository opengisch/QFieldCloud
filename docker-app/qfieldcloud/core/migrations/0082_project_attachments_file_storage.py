# Generated by Django 4.2.19 on 2025-05-06 14:42

from django.db import migrations, models

import qfieldcloud.core.models
import qfieldcloud.core.validators


def set_project_attachments_file_storage(apps, schema_editor):
    Project = apps.get_model("core", "Project")

    Project.objects.update(
        attachments_file_storage=models.F("file_storage"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0081_file_storage_project_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="attachments_file_storage",
            field=models.CharField(
                default=qfieldcloud.core.models.get_project_file_storage_default,
                help_text="Which file storage provider should be used for storing the project attachments files.",
                max_length=100,
                validators=[qfieldcloud.core.validators.file_storage_name_validator],
                verbose_name="Attachments file storage",
            ),
        ),
        migrations.RunPython(
            set_project_attachments_file_storage, migrations.RunPython.noop
        ),
    ]
