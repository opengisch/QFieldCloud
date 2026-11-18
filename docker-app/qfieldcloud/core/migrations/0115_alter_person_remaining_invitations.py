from django.db import migrations, models

import qfieldcloud.core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0114_auto_20261111_1108"),
    ]

    operations = [
        migrations.AlterField(
            model_name="person",
            name="remaining_invitations",
            field=models.PositiveIntegerField(
                default=qfieldcloud.core.models.get_default_remaining_invitations,
                help_text="Remaining invitations that can be sent by the user himself.",
            ),
        ),
    ]
