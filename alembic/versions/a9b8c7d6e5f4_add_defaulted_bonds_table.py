"""add defaulted_bonds table

Revision ID: a9b8c7d6e5f4
Revises: a1d2e3f4b5c6
Create Date: 2026-07-29 01:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "a1d2e3f4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "defaulted_bonds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("default_date", sa.Date(), nullable=False),
        sa.Column("recovery_rate", sa.Float(), nullable=True),
        sa.Column("rating_before", sa.String(length=10), nullable=True),
        sa.Column("rating_after", sa.String(length=10), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin"),
    )
    op.create_index(op.f("ix_defaulted_bonds_isin"), "defaulted_bonds", ["isin"])


def downgrade() -> None:
    op.drop_index(op.f("ix_defaulted_bonds_isin"), table_name="defaulted_bonds")
    op.drop_table("defaulted_bonds")
