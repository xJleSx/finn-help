"""add smart_alert_rules table

Revision ID: d056a6624c86
Revises: c01b61789293
Create Date: 2026-07-01 13:47:44.995083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd056a6624c86'
down_revision: Union[str, Sequence[str], None] = 'c01b61789293'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('smart_alert_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('rule_type', sa.String(length=20), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('condition', sa.String(length=10), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('schedule', sa.String(length=50), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('last_triggered', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_smart_alert_rules_user_id'), 'smart_alert_rules', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_smart_alert_rules_user_id'), table_name='smart_alert_rules')
    op.drop_table('smart_alert_rules')
