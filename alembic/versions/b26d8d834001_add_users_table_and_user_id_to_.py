"""add users table and user_id to portfolio/transactions

Revision ID: b26d8d834001
Revises: 40358fbb008e
Create Date: 2026-06-15 12:54:59.062147

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b26d8d834001'
down_revision: Union[str, Sequence[str], None] = '40358fbb008e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('risk_profile', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)

    with op.batch_alter_table('portfolio') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_unique_constraint('uq_user_portfolio', ['user_id', 'instrument_id'])
        batch_op.create_foreign_key('fk_portfolio_user', 'users', ['user_id'], ['id'])

    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_foreign_key('fk_transactions_user', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_constraint('fk_transactions_user', type_='foreignkey')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('portfolio') as batch_op:
        batch_op.drop_constraint('fk_portfolio_user', type_='foreignkey')
        batch_op.drop_constraint('uq_user_portfolio', type_='unique')
        batch_op.drop_column('user_id')

    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
