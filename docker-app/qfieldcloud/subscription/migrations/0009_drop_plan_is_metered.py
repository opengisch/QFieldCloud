from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscription", "0008_empty_migration"),
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
            reverse_sql="""
                DROP VIEW IF EXISTS current_subscriptions_vw;
            """,
        ),
    ]
