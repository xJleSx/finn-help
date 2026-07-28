"""add rating_agency, rating_date, rating_scale columns to bond_offerings and history

Revision ID: a1d2e3f4b5c6
Revises: d6e5f4a3b2c1
Create Date: 2026-07-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1d2e3f4b5c6"
down_revision: Union[str, Sequence[str], None] = "d6e5f4a3b2c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bond_offerings", sa.Column("rating_agency", sa.String(20), nullable=True, comment="Рейтинговое агентство (ACRA/ExpertRA/Moody's/S&P/Fitch)"))
    op.add_column("bond_offerings", sa.Column("rating_date", sa.Date(), nullable=True, comment="Дата присвоения рейтинга"))
    op.add_column("bond_offerings", sa.Column("rating_scale", sa.String(10), nullable=True, comment="Шкала рейтинга (national/international)"))
    op.add_column("bond_offering_history", sa.Column("rating_agency", sa.String(20), nullable=True, comment="Рейтинговое агентство (ACRA/ExpertRA/Moody's/S&P/Fitch)"))
    op.add_column("bond_offering_history", sa.Column("rating_date", sa.Date(), nullable=True, comment="Дата присвоения рейтинга"))
    op.add_column("bond_offering_history", sa.Column("rating_scale", sa.String(10), nullable=True, comment="Шкала рейтинга (national/international)"))


def downgrade() -> None:
    op.drop_column("bond_offering_history", "rating_scale")
    op.drop_column("bond_offering_history", "rating_date")
    op.drop_column("bond_offering_history", "rating_agency")
    op.drop_column("bond_offerings", "rating_scale")
    op.drop_column("bond_offerings", "rating_date")
    op.drop_column("bond_offerings", "rating_agency")
