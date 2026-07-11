"""merge two heads

Revision ID: d0c71cefc5f1
Revises: d4e5f6a7b8c9, 7bec922bbd1a
Create Date: 2026-07-09 23:08:49.737618

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'd0c71cefc5f1'
down_revision: Union[str, Sequence[str], None] = ('d4e5f6a7b8c9', '7bec922bbd1a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
