"""add channel_preferences table

Revision ID: 3ca2954675b9
Revises: 79725bdf7d8c
Create Date: 2026-06-30 23:45:05.291464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3ca2954675b9'
down_revision: Union[str, Sequence[str], None] = '79725bdf7d8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('channel_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('min_severity', sa.String(length=20), nullable=True),
        sa.Column('quiet_hours_start', sa.String(length=5), nullable=True),
        sa.Column('quiet_hours_end', sa.String(length=5), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'channel', name='uq_user_channel')
    )
    op.create_index(op.f('ix_channel_preferences_user_id'), 'channel_preferences', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_channel_preferences_user_id'), table_name='channel_preferences')
    op.drop_table('channel_preferences')
