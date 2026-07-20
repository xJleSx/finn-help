from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.db.connection import _is_postgres
from src.db.connection import settings as _conn_settings
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


def _get_dialect_insert() -> Any:
    if _is_postgres(_conn_settings.database_url):
        return pg_insert
    return sqlite_insert


def bulk_upsert(
    db: Session,
    model: Any,
    rows: list[dict[str, Any]],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    chunk_size: int = 500,
) -> int:
    """Idempotent upsert using INSERT ... ON CONFLICT.

    PostgreSQL: uses ON CONFLICT (conflict_columns) DO UPDATE SET ...
    SQLite 3.24+: uses ON CONFLICT (conflict_columns) DO UPDATE SET ...

    Returns number of rows processed.
    """
    if not rows:
        return 0

    table: Table = model.__table__
    dialect_insert = _get_dialect_insert()
    pk_cols = [c.name for c in table.primary_key.columns]
    actual_conflict = [c for c in conflict_columns if c not in pk_cols and c in [col.name for col in table.columns]]
    if not actual_conflict:
        actual_conflict = conflict_columns

    processed = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = dialect_insert(model).values(chunk)

        if update_columns:
            update_dict = {col: stmt.excluded[col] for col in update_columns if col in stmt.excluded}
            if update_dict:
                stmt = stmt.on_conflict_do_update(
                    index_elements=actual_conflict,
                    set_=update_dict,
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=actual_conflict)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=actual_conflict)

        try:
            db.execute(stmt)
            processed += len(chunk)
        except Exception as e:
            logger.warning("bulk_upsert chunk failed for %s: %s — falling back to individual inserts", model.__tablename__, e)
            for row in chunk:
                try:
                    fallback = dialect_insert(model).values([row]).on_conflict_do_nothing(index_elements=actual_conflict)
                    db.execute(fallback)
                    processed += 1
                except Exception as inner:
                    logger.debug("bulk_upsert individual row failed: %s", inner)

    return processed


def get_instrument(db: Session, ticker: str) -> Optional[Instrument]:
    """Get an instrument by ticker (case-insensitive, uppercase normalized)."""
    return db.query(Instrument).filter_by(ticker=ticker.upper().strip()).first()


def get_instrument_by_id(db: Session, instrument_id: int) -> Optional[Instrument]:
    """Get an instrument by primary key."""
    return db.query(Instrument).filter_by(id=instrument_id).first()


def get_latest_price(db: Session, instrument_id: int) -> Optional[Price]:
    """Get the most recent price for an instrument."""
    return db.query(Price).filter_by(instrument_id=instrument_id).order_by(Price.date.desc()).first()


def get_price_history(
    db: Session,
    instrument_id: int,
    limit: int = 21,
) -> list[Price]:
    """Get recent price history (newest first)."""
    return db.query(Price).filter_by(instrument_id=instrument_id).order_by(Price.date.desc()).limit(limit).all()


# ── Async versions for scheduler / async contexts ──────────────────────────


async def async_bulk_upsert(
    db: AsyncSession,
    model: Any,
    rows: list[dict[str, Any]],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    chunk_size: int = 500,
) -> int:
    if not rows:
        return 0

    table: Table = model.__table__
    dialect_insert = _get_dialect_insert()
    pk_cols = [c.name for c in table.primary_key.columns]
    actual_conflict = [c for c in conflict_columns if c not in pk_cols and c in [col.name for col in table.columns]]
    if not actual_conflict:
        actual_conflict = conflict_columns

    processed = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = dialect_insert(model).values(chunk)

        if update_columns:
            update_dict = {col: stmt.excluded[col] for col in update_columns if col in stmt.excluded}
            if update_dict:
                stmt = stmt.on_conflict_do_update(
                    index_elements=actual_conflict,
                    set_=update_dict,
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=actual_conflict)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=actual_conflict)

        try:
            await db.execute(stmt)
            processed += len(chunk)
        except Exception as e:
            logger.warning("async_bulk_upsert chunk failed for %s: %s", model.__tablename__, e)
            for row in chunk:
                try:
                    fallback = dialect_insert(model).values([row]).on_conflict_do_nothing(index_elements=actual_conflict)
                    await db.execute(fallback)
                    processed += 1
                except Exception as inner:
                    logger.debug("async_bulk_upsert individual row failed: %s", inner)

    return processed


async def async_get_instrument(db: AsyncSession, ticker: str) -> Optional[Instrument]:
    result = await db.execute(select(Instrument).filter_by(ticker=ticker.upper().strip()))
    return result.scalars().first()


async def async_get_instrument_by_id(db: AsyncSession, instrument_id: int) -> Optional[Instrument]:
    result = await db.execute(select(Instrument).filter_by(id=instrument_id))
    return result.scalars().first()


async def async_get_latest_price(db: AsyncSession, instrument_id: int) -> Optional[Price]:
    result = await db.execute(
        select(Price).filter_by(instrument_id=instrument_id).order_by(Price.date.desc()).limit(1)
    )
    return result.scalars().first()


async def async_get_price_history(
    db: AsyncSession,
    instrument_id: int,
    limit: int = 21,
) -> list[Price]:
    result = await db.execute(
        select(Price).filter_by(instrument_id=instrument_id).order_by(Price.date.desc()).limit(limit)
    )
    return list(result.scalars().all())
