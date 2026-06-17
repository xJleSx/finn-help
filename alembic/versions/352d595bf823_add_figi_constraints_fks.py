"""add figi constraints fks

Revision ID: 352d595bf823
Revises: 55e690c47941
Create Date: 2026-06-17 16:56:45.467799

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '352d595bf823'
down_revision: Union[str, Sequence[str], None] = '55e690c47941'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('portfolio') as batch_op:
        batch_op.create_foreign_key('fk_portfolio_user', 'users', ['user_id'], ['id'])

    with op.batch_alter_table('transactions') as batch_op:
        batch_op.create_foreign_key('fk_transactions_user', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_constraint('fk_transactions_user', type_='foreignkey')

    with op.batch_alter_table('portfolio') as batch_op:
        batch_op.drop_constraint('fk_portfolio_user', type_='foreignkey')
