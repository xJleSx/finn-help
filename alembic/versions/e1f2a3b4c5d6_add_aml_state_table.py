"""add aml_state table for persistent AML compliance

Revision ID: e1f2a3b4c5d6
Revises: 0d5f4166718e
Create Date: 2026-07-23 00:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = '0d5f4166718e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('aml_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('daily_volume', sa.Float(), nullable=True),
        sa.Column('tx_timestamps_json', sa.JSON(), nullable=True),
        sa.Column('velocity_timestamps_json', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_aml_state_user_id'), 'aml_state', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_aml_state_user_id'), table_name='aml_state')
    op.drop_table('aml_state')
