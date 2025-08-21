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
        migrations.RunSQL(
            sql="""
                DROP VIEW IF EXISTS current_subscriptions_vw;
                CREATE VIEW current_subscriptions_vw AS
                SELECT
                    *
                FROM subscription_subscription
                WHERE active_since < now()
                  AND (active_until IS NULL OR active_until > now());
            """,
        ),
    ]
