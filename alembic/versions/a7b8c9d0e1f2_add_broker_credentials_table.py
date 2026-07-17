"""add broker_credentials table

Revision ID: a7b8c9d0e1f2
Revises: 5932f2d8e9af
Create Date: 2026-07-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = '5932f2d8e9af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('broker_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('broker_name', sa.String(length=20), nullable=False),
        sa.Column('token_encrypted', sa.Text(), nullable=False),
        sa.Column('token_type', sa.String(length=20), nullable=True, server_default='access'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'broker_name', 'token_type', name='uq_user_broker_token')
    )
    op.create_index('ix_broker_credentials_user_id', 'broker_credentials', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_broker_credentials_user_id')
    op.drop_table('broker_credentials')
