"""add_totp_fields_to_users

Revision ID: 0d5f4166718e
Revises: a7b8c9d0e1f2
Create Date: 2026-07-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '0d5f4166718e'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(length=32), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('users', sa.Column('recovery_codes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'recovery_codes')
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')
