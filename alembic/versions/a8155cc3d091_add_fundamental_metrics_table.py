"""add fundamental_metrics table

Revision ID: a8155cc3d091
Revises: 87ed6b3d580d
Create Date: 2026-06-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "a8155cc3d091"
down_revision: Union[str, None] = "87ed6b3d580d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "fundamental_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.BigInteger(), nullable=True),
        sa.Column("pe_ratio", sa.Float(), nullable=True),
        sa.Column("pb_ratio", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("eps", sa.Float(), nullable=True),
        sa.Column("debt_equity", sa.Float(), nullable=True),
        sa.Column("book_value", sa.Float(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("net_income", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fundamental_metrics_instr_date", "fundamental_metrics", ["instrument_id", "date"])
    op.create_index("ix_fundamental_metrics_instrument_id", "fundamental_metrics", ["instrument_id"])
    op.create_index("ix_fundamental_metrics_date", "fundamental_metrics", ["date"])


def downgrade():
    op.drop_index("ix_fundamental_metrics_date", table_name="fundamental_metrics")
    op.drop_index("ix_fundamental_metrics_instrument_id", table_name="fundamental_metrics")
    op.drop_index("ix_fundamental_metrics_instr_date", table_name="fundamental_metrics")
    op.drop_table("fundamental_metrics")
