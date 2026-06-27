"""add_financial_reports_and_bond_offerings

Revision ID: 7bec922bbd1a
Revises: b1c2d3e4f5a6
Create Date: 2026-06-26 00:43:11.197051

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bec922bbd1a"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bond_offerings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("offering_date", sa.Date(), nullable=False),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("coupon_type", sa.String(length=20), nullable=False),
        sa.Column("coupon_rate", sa.Float(), nullable=True),
        sa.Column("coupon_period_days", sa.Integer(), nullable=True),
        sa.Column("spread_to_key_rate", sa.Float(), nullable=True),
        sa.Column("yield_to_maturity", sa.Float(), nullable=True),
        sa.Column("duration_years", sa.Float(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("maturity_years", sa.Float(), nullable=True),
        sa.Column("credit_rating", sa.String(length=10), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("has_amortization", sa.Boolean(), nullable=True),
        sa.Column("has_offer", sa.Boolean(), nullable=True),
        sa.Column("min_lot_rub", sa.Float(), nullable=True),
        sa.Column("qual_investor_only", sa.Boolean(), nullable=True),
        sa.Column("nominal_price", sa.Float(), nullable=True),
        sa.Column("current_price_pct", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "isin", name="uq_bond_offering_isin"),
    )
    op.create_index(op.f("ix_bond_offerings_isin"), "bond_offerings", ["isin"], unique=False)
    op.create_index(op.f("ix_bond_offerings_instrument_id"), "bond_offerings", ["instrument_id"], unique=False)

    op.create_table(
        "financial_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("net_profit", sa.Float(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("net_interest_income", sa.Float(), nullable=True),
        sa.Column("operating_income", sa.Float(), nullable=True),
        sa.Column("total_assets", sa.Float(), nullable=True),
        sa.Column("total_liabilities", sa.Float(), nullable=True),
        sa.Column("total_equity", sa.Float(), nullable=True),
        sa.Column("loan_portfolio", sa.Float(), nullable=True),
        sa.Column("customer_deposits", sa.Float(), nullable=True),
        sa.Column("cost_income_ratio", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("roa", sa.Float(), nullable=True),
        sa.Column("net_margin", sa.Float(), nullable=True),
        sa.Column("npl_ratio", sa.Float(), nullable=True),
        sa.Column("provision_coverage", sa.Float(), nullable=True),
        sa.Column("capital_adequacy", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "report_date", "period_type", name="uq_fin_report_date"),
    )
    op.create_index(op.f("ix_financial_reports_instrument_id"), "financial_reports", ["instrument_id"], unique=False)
    op.create_index(op.f("ix_financial_reports_report_date"), "financial_reports", ["report_date"], unique=False)
    op.create_index(
        "ix_financial_reports_instr_date", "financial_reports", ["instrument_id", "report_date"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_financial_reports_instr_date", table_name="financial_reports")
    op.drop_index(op.f("ix_financial_reports_report_date"), table_name="financial_reports")
    op.drop_index(op.f("ix_financial_reports_instrument_id"), table_name="financial_reports")
    op.drop_table("financial_reports")

    op.drop_index(op.f("ix_bond_offerings_instrument_id"), table_name="bond_offerings")
    op.drop_index(op.f("ix_bond_offerings_isin"), table_name="bond_offerings")
    op.drop_table("bond_offerings")
