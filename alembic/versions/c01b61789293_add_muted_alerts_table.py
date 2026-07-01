"""add muted_alerts table

Revision ID: c01b61789293
Revises: 3ca2954675b9
Create Date: 2026-07-01 12:48:10.104136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c01b61789293'
down_revision: Union[str, Sequence[str], None] = '3ca2954675b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('muted_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('alert_type', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'ticker', 'alert_type', name='uq_user_muted_alert')
    )
    op.create_index(op.f('ix_muted_alerts_user_id'), 'muted_alerts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_muted_alerts_user_id'), table_name='muted_alerts')
    op.drop_table('muted_alerts')
