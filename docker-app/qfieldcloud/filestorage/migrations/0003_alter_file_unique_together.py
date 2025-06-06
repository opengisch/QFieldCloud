# Generated by Django 4.2.19 on 2025-05-23 12:56

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0082_project_attachments_file_storage"),
        ("filestorage", "0002_file_file_storage"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="file",
            unique_together={("project", "name", "file_type", "package_job")},
        ),
    ]
