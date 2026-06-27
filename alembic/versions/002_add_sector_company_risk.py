"""Add sector and company risk tracking tables

Revision ID: 002_add_sector_company_risk
Revises: 001_expand_news
Create Date: 2026-06-28 01:25:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_add_sector_company_risk"
down_revision: Union[str, Sequence[str], None] = "001_expand_news"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Add sector impact and risk tracking tables."""
    # news_sector_impacts: tracks how each news affects sectors
    op.create_table(
        "news_sector_impacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id"), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=False),
        sa.Column("impact_type", sa.String(length=50), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_sector_impacts_news", "news_sector_impacts", ["news_id"], unique=False)
    op.create_index("ix_news_sector_impacts_sector", "news_sector_impacts", ["sector"], unique=False)
    op.create_index("ix_news_sector_impacts_type", "news_sector_impacts", ["impact_type"], unique=False)

    # news_company_impacts: tracks how each news affects companies
    op.create_table(
        "news_company_impacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("news_id", sa.Integer(), sa.ForeignKey("news.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("impact_type", sa.String(length=50), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_company_impacts_news", "news_company_impacts", ["news_id"], unique=False)
    op.create_index("ix_news_company_impacts_instrument", "news_company_impacts", ["instrument_id"], unique=False)

    # sector_risk_history: daily risk scores for sectors
    op.create_table(
        "sector_risk_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("components_json", sa.JSON(), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector", "date", name="uq_sector_risk_date"),
    )
    op.create_index("ix_sector_risk_sector_date", "sector_risk_history", ["sector", "date"], unique=False)

    # company_risk_history: daily risk scores for instruments
    op.create_table(
        "company_risk_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("sector_risk", sa.Float(), nullable=True),
        sa.Column("geopolitical_risk", sa.Float(), nullable=True),
        sa.Column("macro_risk", sa.Float(), nullable=True),
        sa.Column("company_specific_risk", sa.Float(), nullable=True),
        sa.Column("components_json", sa.JSON(), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "date", name="uq_company_risk_date"),
    )
    op.create_index("ix_company_risk_instrument_date", "company_risk_history", ["instrument_id", "date"], unique=False)

    # geopolitical_risk_history: daily geopolitical risk with subcategories
    op.create_table(
        "geopolitical_risk_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("sanctions_score", sa.Float(), nullable=True),
        sa.Column("conflict_score", sa.Float(), nullable=True),
        sa.Column("trade_war_score", sa.Float(), nullable=True),
        sa.Column("diplomacy_score", sa.Float(), nullable=True),
        sa.Column("components_json", sa.JSON(), nullable=True),
        sa.Column("sources_json", sa.JSON(), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_geopolitical_risk_date"),
    )
    op.create_index("ix_geopolitical_risk_date", "geopolitical_risk_history", ["date"], unique=False)


def downgrade() -> None:
    """Downgrade schema: Remove risk tracking tables."""
    # Drop indexes
    op.drop_index("ix_geopolitical_risk_date", table_name="geopolitical_risk_history")
    op.drop_index("ix_company_risk_instrument_date", table_name="company_risk_history")
    op.drop_index("ix_sector_risk_sector_date", table_name="sector_risk_history")
    op.drop_index("ix_news_company_impacts_instrument", table_name="news_company_impacts")
    op.drop_index("ix_news_company_impacts_news", table_name="news_company_impacts")
    op.drop_index("ix_news_sector_impacts_type", table_name="news_sector_impacts")
    op.drop_index("ix_news_sector_impacts_sector", table_name="news_sector_impacts")
    op.drop_index("ix_news_sector_impacts_news", table_name="news_sector_impacts")

    # Drop tables
    op.drop_table("geopolitical_risk_history")
    op.drop_table("company_risk_history")
    op.drop_table("sector_risk_history")
    op.drop_table("news_company_impacts")
    op.drop_table("news_sector_impacts")
