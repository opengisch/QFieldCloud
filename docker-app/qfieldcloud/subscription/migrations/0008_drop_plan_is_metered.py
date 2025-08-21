from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscription", "0007_plan_is_seat_flexible_and_more"),
        ("billing", "0019_remove_billingplan_price_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="plan",
            name="is_metered",
        ),
    ]
