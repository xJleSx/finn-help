"""initial — create all base tables

Revision ID: 2516b427423c
Revises: 
Create Date: 2026-06-15 00:36:37.755660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2516b427423c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('instruments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('isin', sa.String(length=12), nullable=True),
        sa.Column('sector', sa.String(length=100), nullable=True),
        sa.Column('instrument_type', sa.String(length=20), nullable=False, server_default='stock'),
        sa.Column('lot_size', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('currency', sa.String(length=3), nullable=True, server_default='RUB'),
        sa.Column('moex_uid', sa.String(length=50), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_instruments_ticker', 'instruments', ['ticker'], unique=True)

    op.create_table('prices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', 'date', name='uq_price_date'),
    )
    op.create_index('ix_prices_instrument_date', 'prices', ['instrument_id', 'date'])

    op.create_table('dividends',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True, server_default='RUB'),
        sa.Column('tax_rate', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', 'date', 'amount', name='uq_dividend'),
    )

    op.create_table('indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('rsi', sa.Float(), nullable=True),
        sa.Column('macd_line', sa.Float(), nullable=True),
        sa.Column('macd_signal', sa.Float(), nullable=True),
        sa.Column('macd_hist', sa.Float(), nullable=True),
        sa.Column('sma_20', sa.Float(), nullable=True),
        sa.Column('sma_50', sa.Float(), nullable=True),
        sa.Column('sma_200', sa.Float(), nullable=True),
        sa.Column('bb_upper', sa.Float(), nullable=True),
        sa.Column('bb_lower', sa.Float(), nullable=True),
        sa.Column('bb_mid', sa.Float(), nullable=True),
        sa.Column('volume_sma_20', sa.Float(), nullable=True),
        sa.Column('atr', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', 'date', name='uq_indicator'),
    )
    op.create_index('ix_indicators_instrument_date', 'indicators', ['instrument_id', 'date'])

    op.create_table('predictions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('target_price', sa.Float(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('features_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('technical_json', sa.JSON(), nullable=True),
        sa.Column('fundamental_json', sa.JSON(), nullable=True),
        sa.Column('geo_json', sa.JSON(), nullable=True),
        sa.Column('fused_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('news',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=True),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('sentiment_score', sa.Float(), nullable=True),
        sa.Column('sentiment_weighted', sa.Float(), nullable=True),
        sa.Column('sentiment_bert_score', sa.Float(), nullable=True),
        sa.Column('source_weight', sa.Float(), nullable=True),
        sa.Column('source_type', sa.String(length=10), nullable=False),
        sa.Column('source_name', sa.String(length=100), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url'),
    )

    op.create_table('news_instruments',
        sa.Column('news_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.ForeignKeyConstraint(['news_id'], ['news.id'], ),
        sa.PrimaryKeyConstraint('news_id', 'instrument_id'),
    )

    op.create_table('geo_risk_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('components_json', sa.JSON(), nullable=True),
        sa.Column('sources_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date'),
    )

    op.create_table('macro_indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('indicator_type', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', 'indicator_type', name='uq_macro_date_type'),
    )
    op.create_index('ix_macro_type_date', 'macro_indicators', ['indicator_type', 'date'])

    op.create_table('relations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('source_id', sa.String(length=100), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('target_id', sa.String(length=100), nullable=False),
        sa.Column('relation_type', sa.String(length=50), nullable=False),
        sa.Column('weight', sa.Float(), nullable=True, server_default='1.0'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_relations_source', 'relations', ['source_type', 'source_id'])
    op.create_index('ix_relations_target', 'relations', ['target_type', 'target_id'])

    op.create_table('user_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table('portfolio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('avg_price', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'instrument_id', name='uq_user_portfolio'),
    )

    op.create_table('transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=4), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=True),
        sa.Column('commission', sa.Float(), nullable=True, server_default='0.0'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('transactions')
    op.drop_table('portfolio')
    op.drop_table('user_settings')
    op.drop_table('relations')
    op.drop_index('ix_macro_type_date', table_name='macro_indicators')
    op.drop_table('macro_indicators')
    op.drop_table('geo_risk_scores')
    op.drop_table('news_instruments')
    op.drop_table('news')
    op.drop_table('signals')
    op.drop_table('predictions')
    op.drop_index('ix_indicators_instrument_date', table_name='indicators')
    op.drop_table('indicators')
    op.drop_table('dividends')
    op.drop_index('ix_prices_instrument_date', table_name='prices')
    op.drop_table('prices')
    op.drop_index('ix_instruments_ticker', table_name='instruments')
    op.drop_table('instruments')
