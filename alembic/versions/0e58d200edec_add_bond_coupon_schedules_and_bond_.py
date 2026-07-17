"""add bond_coupon_schedules and bond_offering_history

Revision ID: 0e58d200edec
Revises: d0c71cefc5f1
Create Date: 2026-07-11 11:10:39.081821

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0e58d200edec'
down_revision: Union[str, Sequence[str], None] = 'd0c71cefc5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('bond_coupon_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('coupon_date', sa.Date(), nullable=False),
        sa.Column('coupon_value', sa.Float(), nullable=False, comment='Coupon amount in RUB'),
        sa.Column('coupon_number', sa.Integer(), nullable=True, comment='Coupon sequence number'),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('fix_date', sa.Date(), nullable=True, comment='Rate fix date (for floaters)'),
        sa.Column('face_value', sa.Float(), nullable=True, comment='Face value at time of payment (for amortization)'),
        sa.Column('initial_face_value', sa.Float(), nullable=True, comment='Initial face value'),
        sa.Column('is_amortization', sa.Boolean(), nullable=True, comment='True if this is an amortization payment'),
        sa.Column('paid', sa.Boolean(), nullable=True, comment='Whether the coupon has been paid'),
        sa.Column('extra', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', 'coupon_date', 'coupon_number', name='uq_bond_coupon')
    )
    op.create_index('ix_bond_coupon_date', 'bond_coupon_schedules', ['coupon_date'], unique=False)
    op.create_index(op.f('ix_bond_coupon_schedules_instrument_id'), 'bond_coupon_schedules', ['instrument_id'], unique=False)

    op.create_table('bond_offering_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('offering_date', sa.Date(), nullable=False),
        sa.Column('isin', sa.String(length=12), nullable=True),
        sa.Column('coupon_type', sa.String(length=20), nullable=True),
        sa.Column('coupon_rate', sa.Float(), nullable=True, comment='Ставка купона % годовых'),
        sa.Column('coupon_period_days', sa.Integer(), nullable=True, comment='Купонный период в днях'),
        sa.Column('yield_to_maturity', sa.Float(), nullable=True, comment='YTM %'),
        sa.Column('duration_years', sa.Float(), nullable=True, comment='Дюрация в годах'),
        sa.Column('spread_to_key_rate', sa.Float(), nullable=True, comment='Спред к ключевой ставке'),
        sa.Column('maturity_date', sa.Date(), nullable=True, comment='Дата погашения'),
        sa.Column('maturity_years', sa.Float(), nullable=True, comment='Срок обращения в годах'),
        sa.Column('credit_rating', sa.String(length=10), nullable=True, comment='Кредитный рейтинг'),
        sa.Column('current_price_pct', sa.Float(), nullable=True, comment='Цена в % от номинала'),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bond_offering_history_instr_date', 'bond_offering_history', ['instrument_id', 'snapshot_date'], unique=False)
    op.create_index(op.f('ix_bond_offering_history_instrument_id'), 'bond_offering_history', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_bond_offering_history_isin'), 'bond_offering_history', ['isin'], unique=False)


def downgrade() -> None:
    op.drop_table('bond_offering_history')
    op.drop_table('bond_coupon_schedules')
