from django_migrate_sql.config import SQLItem

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
                s.id,
                s.uuid,
                s.regular_plan_id,
                CASE
                    WHEN s.trial_expires_at > now() AND s.trial_plan_id IS NOT NULL
                    THEN s.trial_plan_id
                    ELSE s.regular_plan_id
                END AS active_plan_id,
                s.purchased_seats,
                s.account_id,
                s.status,
                s.created_by_id,
                s.created_at,
                s.updated_at,
                s.requested_cancel_at,
                s.active_since,
                s.active_until,
                s.billing_cycle_anchor_at,
                s.current_period_since,
                s.current_period_until,
                s.notes,
                s.trial_plan_id,
                s.trial_expires_at
            FROM subscription_subscription s
            WHERE s.active_since < now()
            AND (s.active_until IS NULL OR s.active_until > now());
        """,
        r"""
            DROP VIEW current_subscriptions_vw
        """,
    ),
]
