"""Expand news schema for categorization and deduplication

Revision ID: 001_expand_news
Revises: b52c52467be4
Create Date: 2026-06-28 01:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_expand_news"
down_revision: Union[str, Sequence[str], None] = "7bec922bbd1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Add categorization and deduplication fields to news."""
    # Add new columns to news table
    op.add_column(
        "news",
        sa.Column("category", sa.String(length=50), nullable=True, default="UNCLASSIFIED"),
    )
    op.add_column(
        "news",
        sa.Column("subcategory", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "news",
        sa.Column("sentiment", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "news",
        sa.Column("impact_score", sa.Float(), nullable=True, default=0.0),
    )
    op.add_column(
        "news",
        sa.Column("event_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "news",
        sa.Column("is_relevant", sa.Boolean(), nullable=True, default=True),
    )
    op.add_column(
        "news",
        sa.Column("embedding", sa.JSON(), nullable=True),
    )
    op.add_column(
        "news",
        sa.Column("source_count", sa.Integer(), nullable=True, default=1),
    )
    op.add_column(
        "news",
        sa.Column("updated_at", sa.DateTime(), nullable=True, default=sa.func.now()),
    )

    # Create indexes for faster filtering and categorization
    op.create_index("ix_news_category", "news", ["category"], unique=False)
    op.create_index("ix_news_subcategory", "news", ["subcategory"], unique=False)
    op.create_index("ix_news_event_id", "news", ["event_id"], unique=False)
    op.create_index("ix_news_is_relevant", "news", ["is_relevant"], unique=False)
    op.create_index("ix_news_created_at", "news", ["created_at"], unique=False)

    # Create news_events table for event clustering
    op.create_table(
        "news_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("subcategory", sa.String(length=100), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True, default=0.0),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=True, default=1),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_events_category", "news_events", ["category"], unique=False)
    op.create_index("ix_news_events_created_at", "news_events", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema: Remove new columns and tables."""
    # Drop news_events table
    op.drop_table("news_events")

    # Drop indexes
    op.drop_index("ix_news_created_at", table_name="news")
    op.drop_index("ix_news_is_relevant", table_name="news")
    op.drop_index("ix_news_event_id", table_name="news")
    op.drop_index("ix_news_subcategory", table_name="news")
    op.drop_index("ix_news_category", table_name="news")

    # Remove columns
    op.drop_column("news", "updated_at")
    op.drop_column("news", "source_count")
    op.drop_column("news", "embedding")
    op.drop_column("news", "is_relevant")
    op.drop_column("news", "event_id")
    op.drop_column("news", "impact_score")
    op.drop_column("news", "sentiment")
    op.drop_column("news", "subcategory")
    op.drop_column("news", "category")
