"""add_favorites_table

Revision ID: 79725bdf7d8c
Revises: a195f426825e
Create Date: 2026-06-30 23:23:34.052158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '79725bdf7d8c'
down_revision: Union[str, Sequence[str], None] = 'a195f426825e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('favorites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'ticker', name='uq_user_favorite_ticker')
    )
    op.create_index(op.f('ix_favorites_user_id'), 'favorites', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_favorites_user_id'), table_name='favorites')
    op.drop_table('favorites')
