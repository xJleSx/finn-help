"""Add sector and company risk tables.

This migration was lost from the versions directory.
It is recreated as a stub to fix the migration chain.
"""

from typing import Sequence, Union

revision: str = "002_add_sector_company_risk"
down_revision: Union[str, Sequence[str], None] = "2516b427423c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
