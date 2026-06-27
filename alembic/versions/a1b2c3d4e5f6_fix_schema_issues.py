"""fix schema issues: figi, notify_trade, signal action length, duplicate index

Revision ID: a1b2c3d4e5f6
Revises: 93001d0a0eed
Create Date: 2026-06-25

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "93001d0a0eed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Add figi column to instruments if not exists
    instruments_columns = [c["name"] for c in inspector.get_columns("instruments")]
    if "figi" not in instruments_columns:
        with op.batch_alter_table("instruments") as batch_op:
            batch_op.add_column(sa.Column("figi", sa.String(50), nullable=True))
            batch_op.create_index("ix_instruments_figi", ["figi"])

    # 2. Add notify_trade column to subscriptions if not exists
    subs_columns = [c["name"] for c in inspector.get_columns("subscriptions")]
    if "notify_trade" not in subs_columns:
        with op.batch_alter_table("subscriptions") as batch_op:
            batch_op.add_column(sa.Column("notify_trade", sa.Boolean(), nullable=True))

    # 3. Widen signals.action for CAUTIOUS_BUY (12 chars)
    signals_columns = [c["name"] for c in inspector.get_columns("signals")]
    if "action" in signals_columns:
        with op.batch_alter_table("signals") as batch_op:
            batch_op.alter_column("action", type_=sa.String(20), existing_type=sa.String(10))

    # 4. Drop duplicate index ix_trade_log_ticker (keep ix_trade_log_tkr)
    indexes_on_trade_log = [i["name"] for i in inspector.get_indexes("trade_log")]
    if "ix_trade_log_ticker" in indexes_on_trade_log:
        with op.batch_alter_table("trade_log") as batch_op:
            batch_op.drop_index("ix_trade_log_ticker")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Re-create duplicate index
    indexes_on_trade_log = [i["name"] for i in inspector.get_indexes("trade_log")]
    if "ix_trade_log_ticker" not in indexes_on_trade_log:
        with op.batch_alter_table("trade_log") as batch_op:
            batch_op.create_index("ix_trade_log_ticker", ["ticker"])

    # Revert signals.action to String(10)
    signals_columns = [c["name"] for c in inspector.get_columns("signals")]
    if "action" in signals_columns:
        with op.batch_alter_table("signals") as batch_op:
            batch_op.alter_column("action", type_=sa.String(10), existing_type=sa.String(20))

    # Remove notify_trade
    subs_columns = [c["name"] for c in inspector.get_columns("subscriptions")]
    if "notify_trade" in subs_columns:
        with op.batch_alter_table("subscriptions") as batch_op:
            batch_op.drop_column("notify_trade")

    # Remove figi
    instruments_columns = [c["name"] for c in inspector.get_columns("instruments")]
    if "figi" in instruments_columns:
        with op.batch_alter_table("instruments") as batch_op:
            batch_op.drop_index("ix_instruments_figi")
            batch_op.drop_column("figi")
