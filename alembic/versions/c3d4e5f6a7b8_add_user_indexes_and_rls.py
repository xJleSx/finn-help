"""add_user_indexes_and_rls

Add user_id indexes for multi-tenant performance and initial RLS setup.
Creates indexes on all tables with user_id that lack them for fast user-scoped queries.

Revision ID: c3d4e5f6a7b8
Revises: b2e409397a74
Create Date: 2026-07-04 22:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2e409397a74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_SCOPED_TABLES = [
    "portfolio",
    "transactions",
    "subscriptions",
    "author_subscriptions",
    "favorites",
    "notifications",
    "channel_preferences",
    "muted_alerts",
    "smart_alert_rules",
    "notification_receipts",
    "alert_log",
    "paper_accounts",
    "paper_orders",
    "paper_trade_log",
]


def upgrade() -> None:
    op.create_index(op.f("ix_portfolio_user_id"), "portfolio", ["user_id"], unique=False)
    op.create_index(op.f("ix_transactions_user_id"), "transactions", ["user_id"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_alert_log_user_id"), "alert_log", ["user_id"], unique=False)
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)
    _run_rls_sql("upgrade")


def downgrade() -> None:
    op.drop_index(op.f("ix_portfolio_user_id"), table_name="portfolio")
    op.drop_index(op.f("ix_transactions_user_id"), table_name="transactions")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_alert_log_user_id"), table_name="alert_log")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    _run_rls_sql("downgrade")


def _run_rls_sql(direction: str) -> None:
    table_array = "ARRAY[" + ",".join(f"'{t}'" for t in USER_SCOPED_TABLES) + "]"

    if direction == "upgrade":
        op.execute(
            sa.text(
                f"""
                DO $$
                DECLARE
                    tbl text;
                    tables text[] := {table_array};
                BEGIN
                    FOREACH tbl IN ARRAY tables
                    LOOP
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = tbl
                              AND column_name = 'user_id'
                        ) THEN
                            BEGIN
                                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
                                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
                                EXECUTE format(
                                    'DROP POLICY IF EXISTS tenant_isolation_policy ON %I',
                                    tbl
                                );
                                EXECUTE format(
                                    'CREATE POLICY tenant_isolation_policy ON %I '
                                    'USING (user_id = current_setting(''app.current_user_id'')::int)',
                                    tbl
                                );
                            EXCEPTION
                                WHEN undefined_table THEN NULL;
                                WHEN feature_not_supported THEN NULL;
                            END;
                        END IF;
                    END LOOP;
                EXCEPTION
                    WHEN feature_not_supported THEN NULL;
                END
                $$;
                """
            ),
        )
    else:
        op.execute(
            sa.text(
                f"""
                DO $$
                DECLARE
                    tbl text;
                    tables text[] := {table_array};
                BEGIN
                    FOREACH tbl IN ARRAY tables
                    LOOP
                        BEGIN
                            EXECUTE format(
                                'DROP POLICY IF EXISTS tenant_isolation_policy ON %I',
                                tbl
                            );
                            EXECUTE format(
                                'ALTER TABLE %I NO FORCE ROW LEVEL SECURITY',
                                tbl
                            );
                            EXECUTE format(
                                'ALTER TABLE %I DISABLE ROW LEVEL SECURITY',
                                tbl
                            );
                        EXCEPTION
                            WHEN undefined_table THEN NULL;
                            WHEN feature_not_supported THEN NULL;
                        END;
                    END LOOP;
                EXCEPTION
                    WHEN feature_not_supported THEN NULL;
                END
                $$;
                """
            ),
        )
