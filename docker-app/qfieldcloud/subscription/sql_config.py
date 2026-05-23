from migrate_sql.config import SQLItem

sql_items = [
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
