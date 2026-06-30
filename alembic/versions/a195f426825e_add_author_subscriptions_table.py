"""add author_subscriptions table

Revision ID: a195f426825e
Revises: b40a7e5076b2
Create Date: 2026-06-30 23:17:40.132366

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a195f426825e'
down_revision: Union[str, Sequence[str], None] = 'b40a7e5076b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('author_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('author_nick', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'author_nick', name='uq_user_author_sub')
    )
    op.create_index('ix_author_sub_author', 'author_subscriptions', ['author_nick'], unique=False)
    op.create_index(op.f('ix_author_subscriptions_user_id'), 'author_subscriptions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_author_subscriptions_user_id'), table_name='author_subscriptions')
    op.drop_index('ix_author_sub_author', table_name='author_subscriptions')
    op.drop_table('author_subscriptions')
