"""Phase 10 — Advanced Trading & Compliance

Adds support for:
- IOC/FOK order types and time_in_force
- Order fills tracking
- Short selling (short_positions table)
- Margin accounts & leverage tracking
- Compliance events logging
- Tax report records

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Orders table enhancements ─────────────────────────────────────
    op.add_column("orders", sa.Column("time_in_force", sa.String(10), nullable=True, server_default="day"))
    op.add_column("orders", sa.Column("filled_quantity", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("orders", sa.Column("remaining_quantity", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("parent_order_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("is_short", sa.Boolean(), nullable=True, server_default="0"))
    op.add_column("orders", sa.Column("margin_used", sa.Float(), nullable=True))
    op.create_foreign_key("fk_orders_parent", "orders", "orders", ["parent_order_id"], ["id"])
    op.create_index("ix_orders_ticker", "orders", ["ticker"], unique=False)
    op.alter_column("orders", "order_type", type_=sa.String(10), existing_type=sa.String(10))

    # ── Order fills table ─────────────────────────────────────────────
    op.create_table(
        "order_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("commission", sa.Float(), nullable=True),
        sa.Column("filled_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_order_fills_order", "order_fills", ["order_id"])

    # ── Short positions table ─────────────────────────────────────────
    op.create_table(
        "short_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="0"),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("margin_held", sa.Float(), nullable=True),
        sa.Column("borrow_rate", sa.Float(), server_default="0.0"),
        sa.Column("opened_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_unique_constraint("uq_short_position_user_ticker", "short_positions", ["user_id", "ticker"])
    op.create_index("ix_short_positions_ticker", "short_positions", ["ticker"])

    # ── Margin accounts table ─────────────────────────────────────────
    op.create_table(
        "margin_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="0"),
        sa.Column("total_loan", sa.Float(), server_default="0.0"),
        sa.Column("margin_used", sa.Float(), server_default="0.0"),
        sa.Column("margin_limit", sa.Float(), server_default="0.0"),
        sa.Column("leverage", sa.Float(), server_default="1.0"),
        sa.Column("status", sa.String(20), server_default="safe"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_unique_constraint("uq_margin_account_user", "margin_accounts", ["user_id"])

    # ── Compliance events table ───────────────────────────────────────
    op.create_table(
        "compliance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="0"),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(20), server_default="info"),
        sa.Column("resolved", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_compliance_events_user", "compliance_events", ["user_id"])
    op.create_index("ix_compliance_events_type", "compliance_events", ["event_type"])

    # ── Tax report records table ──────────────────────────────────────
    op.create_table(
        "tax_report_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="0"),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("total_pnl", sa.Float(), server_default="0.0"),
        sa.Column("total_dividends", sa.Float(), server_default="0.0"),
        sa.Column("total_tax_due", sa.Float(), server_default="0.0"),
        sa.Column("tax_paid", sa.Float(), server_default="0.0"),
        sa.Column("report_data", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_tax_report_user_year", "tax_report_records", ["user_id", "year"])


def downgrade() -> None:
    op.drop_table("tax_report_records")
    op.drop_table("compliance_events")
    op.drop_table("margin_accounts")
    op.drop_table("short_positions")
    op.drop_table("order_fills")
    op.drop_index("ix_orders_ticker", table_name="orders")
    op.drop_constraint("fk_orders_parent", "orders", type_="foreignkey")
    op.drop_column("orders", "margin_used")
    op.drop_column("orders", "is_short")
    op.drop_column("orders", "parent_order_id")
    op.drop_column("orders", "remaining_quantity")
    op.drop_column("orders", "filled_quantity")
    op.drop_column("orders", "time_in_force")
