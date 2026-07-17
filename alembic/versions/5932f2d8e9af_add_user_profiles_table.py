"""add user_profiles table

Revision ID: 5932f2d8e9af
Revises: 0e58d200edec
Create Date: 2026-07-11 11:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '5932f2d8e9af'
down_revision: Union[str, Sequence[str], None] = '0e58d200edec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('risk_profile', sa.String(length=20), nullable=True, server_default='balanced'),
        sa.Column('investment_horizon', sa.String(length=20), nullable=True, server_default='medium'),
        sa.Column('capital', sa.Float(), nullable=True, server_default='100000.0'),
        sa.Column('preferences', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_profiles_user_id')
    )
    op.create_index('ix_user_profiles_user_id', 'user_profiles', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_profiles_user_id')
    op.drop_table('user_profiles')
