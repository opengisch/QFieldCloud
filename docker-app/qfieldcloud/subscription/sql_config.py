from migrate_sql.config import SQLItem

sql_items = [
    SQLItem(
        "subscription_subscription_prevent_overlaps_idx",
        r"""
            ALTER TABLE subscription_subscription
            ADD CONSTRAINT subscription_subscription_prevent_overlaps
            EXCLUDE USING gist (
                account_id WITH =,
                tstzrange(active_since, active_until) WITH &&
            )
            WHERE (active_since IS NOT NULL)
        """,
        r"""
            ALTER TABLE subscription_subscription DROP CONSTRAINT subscription_subscription_prevent_overlaps
        """,
    ),
    SQLItem(
        "subscription_package_prevent_overlaps_idx",
        r"""
            ALTER TABLE subscription_package
            ADD CONSTRAINT subscription_package_prevent_overlaps
            EXCLUDE USING gist (
                subscription_id WITH =,
                tstzrange(active_since, active_until) WITH &&
            )
            WHERE (active_since IS NOT NULL)
        """,
        r"""
            ALTER TABLE subscription_package DROP CONSTRAINT subscription_package_prevent_overlaps
        """,
    ),
    SQLItem(
        "current_subscriptions_vw",
        r"""
            CREATE VIEW current_subscriptions_vw AS
            SELECT
                *
            FROM
                subscription_subscription
            WHERE
                active_since < now()
                AND (
                    active_until IS NULL
                    OR active_until > now()
                )
        """,
        r"""
            DROP VIEW current_subscriptions_vw
        """,
    ),
]
