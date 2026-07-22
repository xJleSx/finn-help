"""add unique constraint for fundamental_metrics upsert

Revision ID: d6e5f4a3b2c1
Revises: e1f2a3b4c5d6
Create Date: 2026-07-23 00:35:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd6e5f4a3b2c1'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fundamental_metrics") as batch_op:
        batch_op.create_unique_constraint(
            "uq_fundamental_metrics_instr_date",
            ["instrument_id", "date"],
        )


def downgrade() -> None:
    with op.batch_alter_table("fundamental_metrics") as batch_op:
        batch_op.drop_constraint("uq_fundamental_metrics_instr_date", type_="unique")
