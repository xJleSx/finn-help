"""add_market_events_table

Revision ID: 93001d0a0eed
Revises: a8155cc3d091
Create Date: 2026-06-23 19:34:20.238071

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93001d0a0eed'
down_revision: Union[str, Sequence[str], None] = 'a8155cc3d091'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('market_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('severity', sa.Float(), nullable=False),
    sa.Column('market_impact_pct', sa.Float(), nullable=True),
    sa.Column('sector_impacts_json', sa.JSON(), nullable=True),
    sa.Column('indicators_before_json', sa.JSON(), nullable=True),
    sa.Column('indicators_after_json', sa.JSON(), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=True),
    sa.Column('source_news_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['source_news_id'], ['news.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_market_events_date'), 'market_events', ['date'], unique=False)
    op.create_index('ix_market_events_date_type', 'market_events', ['date', 'event_type'], unique=False)
    op.create_index(op.f('ix_market_events_event_type'), 'market_events', ['event_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_market_events_event_type'), table_name='market_events')
    op.drop_index('ix_market_events_date_type', table_name='market_events')
    op.drop_index(op.f('ix_market_events_date'), table_name='market_events')
    op.drop_table('market_events')
