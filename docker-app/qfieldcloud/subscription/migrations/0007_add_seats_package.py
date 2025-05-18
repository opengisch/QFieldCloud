from django.db import migrations, models


def create_seats_package(apps, schema_editor):
    PackageType = apps.get_model("subscription", "PackageType")
    if not PackageType.objects.filter(type="seats").exists():
        PackageType.objects.create(
            code="seats_package",
            type="seats",
            display_name="Seats",
            is_public=True,
            min_quantity=1,
            max_quantity=500,
            unit_amount=1,
            unit_label="seat",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("subscription", "0006_auto_20230426_2222"),
    ]

    operations = [
        # Schema change: add 'seats' to choices
        migrations.AlterField(
            model_name="packagetype",
            name="type",
            field=models.CharField(
                choices=[("storage", "Storage"), ("seats", "Seats")],
                max_length=100,
                unique=True,
            ),
        ),
        # Data seeding: create the new PackageType entry
        migrations.RunPython(create_seats_package),
    ]
