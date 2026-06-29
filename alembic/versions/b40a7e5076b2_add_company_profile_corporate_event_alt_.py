"""add company_profile, corporate_event, alt_data_point, alert_log, model_feedback

Revision ID: b40a7e5076b2
Revises: 002_add_sector_company_risk
Create Date: 2026-06-29 08:35:55.706329

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b40a7e5076b2"
down_revision: Union[str, Sequence[str], None] = "002_add_sector_company_risk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alert_log_alert_type"), "alert_log", ["alert_type"], unique=False)
    op.create_index(op.f("ix_alert_log_created_at"), "alert_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_alert_log_ticker"), "alert_log", ["ticker"], unique=False)
    op.create_index("ix_alert_log_ticker_created", "alert_log", ["ticker", "created_at"], unique=False)
    op.create_index("ix_alert_log_type_created", "alert_log", ["alert_type", "created_at"], unique=False)

    op.create_table(
        "alt_data_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(length=50), nullable=False),
        sa.Column("indicator_name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_name", "indicator_name", "date", name="uq_alt_data_point"),
    )
    op.create_index(op.f("ix_alt_data_points_source_name"), "alt_data_points", ["source_name"], unique=False)
    op.create_index("ix_alt_data_source_date", "alt_data_points", ["source_name", "date"], unique=False)

    op.create_table(
        "model_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=50), nullable=False),
        sa.Column("predicted_return", sa.Float(), nullable=False),
        sa.Column("actual_return", sa.Float(), nullable=False),
        sa.Column("prediction_date", sa.DateTime(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("features_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_feedback_created", "model_feedback", ["created_at"], unique=False)
    op.create_index(op.f("ix_model_feedback_model_name"), "model_feedback", ["model_name"], unique=False)
    op.create_index(op.f("ix_model_feedback_ticker"), "model_feedback", ["ticker"], unique=False)
    op.create_index("ix_model_feedback_ticker_name", "model_feedback", ["ticker", "model_name"], unique=False)

    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("employees", sa.Integer(), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("industry_description", sa.Text(), nullable=True),
        sa.Column("registrar", sa.String(length=100), nullable=True),
        sa.Column("auditor", sa.String(length=100), nullable=True),
        sa.Column("state_reg_number", sa.String(length=50), nullable=True),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_company_profiles_instrument_id"), "company_profiles", ["instrument_id"], unique=True
    )

    op.create_table(
        "corporate_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("announcement_date", sa.Date(), nullable=True),
        sa.Column("ex_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("dividend_amount", sa.Float(), nullable=True),
        sa.Column("dividend_currency", sa.String(length=3), nullable=True),
        sa.Column("dividend_tax_rate", sa.Float(), nullable=True),
        sa.Column("buyback_volume", sa.Float(), nullable=True),
        sa.Column("buyback_shares", sa.Float(), nullable=True),
        sa.Column("buyback_price", sa.Float(), nullable=True),
        sa.Column("split_ratio_from", sa.Integer(), nullable=True),
        sa.Column("split_ratio_to", sa.Integer(), nullable=True),
        sa.Column("emission_volume", sa.Float(), nullable=True),
        sa.Column("emission_shares", sa.Float(), nullable=True),
        sa.Column("emission_price", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corporate_event_instr_date", "corporate_events",
        ["instrument_id", "announcement_date"], unique=False,
    )
    op.create_index(
        "ix_corporate_event_type_date", "corporate_events",
        ["event_type", "announcement_date"], unique=False,
    )
    op.create_index(
        op.f("ix_corporate_events_announcement_date"), "corporate_events",
        ["announcement_date"], unique=False,
    )
    op.create_index(op.f("ix_corporate_events_event_type"), "corporate_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_corporate_events_instrument_id"), "corporate_events", ["instrument_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_corporate_events_instrument_id"), table_name="corporate_events")
    op.drop_index(op.f("ix_corporate_events_event_type"), table_name="corporate_events")
    op.drop_index(op.f("ix_corporate_events_announcement_date"), table_name="corporate_events")
    op.drop_index("ix_corporate_event_type_date", table_name="corporate_events")
    op.drop_index("ix_corporate_event_instr_date", table_name="corporate_events")
    op.drop_table("corporate_events")
    op.drop_index(op.f("ix_company_profiles_instrument_id"), table_name="company_profiles")
    op.drop_table("company_profiles")
    op.drop_index("ix_model_feedback_ticker_name", table_name="model_feedback")
    op.drop_index(op.f("ix_model_feedback_ticker"), table_name="model_feedback")
    op.drop_index(op.f("ix_model_feedback_model_name"), table_name="model_feedback")
    op.drop_index("ix_model_feedback_created", table_name="model_feedback")
    op.drop_table("model_feedback")
    op.drop_index("ix_alt_data_source_date", table_name="alt_data_points")
    op.drop_index(op.f("ix_alt_data_points_source_name"), table_name="alt_data_points")
    op.drop_table("alt_data_points")
    op.drop_index("ix_alert_log_type_created", table_name="alert_log")
    op.drop_index("ix_alert_log_ticker_created", table_name="alert_log")
    op.drop_index(op.f("ix_alert_log_ticker"), table_name="alert_log")
    op.drop_index(op.f("ix_alert_log_created_at"), table_name="alert_log")
    op.drop_index(op.f("ix_alert_log_alert_type"), table_name="alert_log")
    op.drop_table("alert_log")
