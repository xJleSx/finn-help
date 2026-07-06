from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.models import Instrument, Price


def get_instrument(db: Session, ticker: str) -> Optional[Instrument]:
    """Get an instrument by ticker (case-insensitive, uppercase normalized)."""
    return db.query(Instrument).filter_by(ticker=ticker.upper().strip()).first()


def get_instrument_by_id(db: Session, instrument_id: int) -> Optional[Instrument]:
    """Get an instrument by primary key."""
    return db.query(Instrument).filter_by(id=instrument_id).first()


def get_latest_price(db: Session, instrument_id: int) -> Optional[Price]:
    """Get the most recent price for an instrument."""
    return (
        db.query(Price)
        .filter_by(instrument_id=instrument_id)
        .order_by(Price.date.desc())
        .first()
    )


def get_price_history(
    db: Session,
    instrument_id: int,
    limit: int = 21,
) -> list[Price]:
    """Get recent price history (newest first)."""
    return (
        db.query(Price)
        .filter_by(instrument_id=instrument_id)
        .order_by(Price.date.desc())
        .limit(limit)
        .all()
    )
