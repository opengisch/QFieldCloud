# Generated by Django 4.2.16 on 2024-11-29 06:28

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    def add_created_by_and_updated_by(apps, schema_editor):
        OrganizationMember = apps.get_model("core", "OrganizationMember")

        for member in OrganizationMember.objects.all():
            member.created_by = member.organization.organization_owner
            member.updated_by = member.organization.organization_owner
            member.save()

    dependencies = [
        ("core", "0078_alter_project_packaging_offliner"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmember",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="organizationmember",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to=models.Q(("type", 1)),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_organization_members",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="organizationmember",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="organizationmember",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to=models.Q(("type", 1)),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="updated_organization_members",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(add_created_by_and_updated_by, migrations.RunPython.noop),
    ]
