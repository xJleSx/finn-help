"""add notification_receipts table

Revision ID: fffa98744b80
Revises: d056a6624c86
Create Date: 2026-07-01 13:54:29.628607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fffa98744b80'
down_revision: Union[str, Sequence[str], None] = 'd056a6624c86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notification_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('notification_type', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_receipts_user_id'), 'notification_receipts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_receipts_user_id'), table_name='notification_receipts')
    op.drop_table('notification_receipts')
