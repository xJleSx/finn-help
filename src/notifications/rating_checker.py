import logging
from dataclasses import dataclass
from typing import Any, Optional, cast

import requests

from src.db.connection import get_session
from src.db.models import BondOffering, Instrument, Portfolio, Price
from src.interfaces.telegram_helpers import get_portfolio_positions, html_escape

logger = logging.getLogger(__name__)

RATING_ORDER = {
    "AAA": 0, "AA+": 1, "AA": 2, "AA-": 3,
    "A+": 4, "A": 5, "A-": 6,
    "BBB+": 7, "BBB": 8, "BBB-": 9,
    "BB+": 10, "BB": 11, "B+": 12,
    "B": 13, "B-": 14,
    "CCC": 15, "CC": 16, "C": 17, "D": 18,
    "NR": 19,
}

MOEX_RATING_URL = "https://iss.moex.com/iss/securities/{ticker}.json"


@dataclass
class RatingChange:
    ticker: str
    name: str
    old_rating: str
    new_rating: str
    is_downgrade: bool
    position_value: float
    portfolio_pct: float


def check_rating_changes() -> list[RatingChange]:
    changes: list[RatingChange] = []
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            return changes
        total_value = sum(r["value"] for r in rows)
        for r in rows:
            old_rating = _get_stored_rating(db, r["ticker"])
            new_rating = _fetch_rating_from_moex(r["ticker"])
            if not new_rating or not old_rating:
                continue
            if new_rating == old_rating:
                continue
            old_level = RATING_ORDER.get(old_rating.upper(), 19)
            new_level = RATING_ORDER.get(new_rating.upper(), 19)
            is_downgrade = new_level > old_level
            changes.append(RatingChange(
                ticker=r["ticker"],
                name=r.get("name", r["ticker"]),
                old_rating=old_rating,
                new_rating=new_rating,
                is_downgrade=is_downgrade,
                position_value=r["value"],
                portfolio_pct=(r["value"] / total_value * 100) if total_value > 0 else 0,
            ))
            _update_stored_rating(db, r["ticker"], new_rating)
        return changes
    except Exception:
        logger.exception("rating_check_error")
        return changes
    finally:
        db.close()


def _get_stored_rating(db: Any, ticker: str) -> Optional[str]:
    inst = db.query(Instrument).filter_by(ticker=ticker).first()
    if not inst:
        return None
    offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
    if offering and offering.credit_rating:
        return str(offering.credit_rating)
    return None


def _update_stored_rating(db: Any, ticker: str, rating: str) -> None:
    inst = db.query(Instrument).filter_by(ticker=ticker).first()
    if not inst:
        return
    offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
    if not offering:
        return
    offering.credit_rating = rating
    try:
        db.commit()
    except Exception:
        db.rollback()


def _fetch_rating_from_moex(ticker: str) -> Optional[str]:
    try:
        url = MOEX_RATING_URL.format(ticker=ticker)
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        securities = data.get("securities", {})
        rows = securities.get("data", [])
        cols = securities.get("columns", [])
        if "credit_rating" in cols:
            idx = cols.index("credit_rating")
            for row in rows:
                if len(row) > idx and row[idx]:
                    val = str(row[idx]).strip()
                    if val:
                        return val
        return None
    except Exception:
        logger.debug("moex_rating_fetch_failed for %s", ticker)
        return None


def format_rating_alert(change: RatingChange) -> str:
    direction = "ПОНИЖЕНИЕ" if change.is_downgrade else "ПОВЫШЕНИЕ"
    emoji = "🚨" if change.is_downgrade else "✅"
    lines = [
        "{} <b>{}</b> РЕЙТИНГА\n".format(emoji, direction),
        "{} ({})".format(html_escape(change.name), change.ticker),
        "Было: {}".format(change.old_rating),
        "Стало: {}".format(change.new_rating),
        "",
    ]
    if change.is_downgrade:
        pnl = _get_position_pnl(change.ticker)
        lines.append("⚠️ <b>Действие:</b> Рекомендуется ПРОДАЖА")
        if pnl is not None:
            lines.append("💰 Текущий P&L: {:.2f} ₽{}".format(
                pnl,
                " (минимальный убыток)" if abs(pnl) < 1 else "",
            ))
        impact = change.portfolio_pct
        lines.append("")
        lines.append("📉 Риск: При портфеле просадка может составить ~{:.1f}% капитала".format(impact))
        lines.append("")
        lines.append("[Продать] [Подробнее] [Игнорировать 24ч]")
    else:
        lines.append("✅ <b>Действие:</b> Оставить в портфеле")
    return "\n".join(lines)


def _get_position_pnl(ticker: str) -> Optional[float]:
    db = get_session()
    try:
        pos = db.query(Portfolio).join(Instrument).filter(Instrument.ticker == ticker).first()
        if not pos:
            return None
        price_rec = db.query(Price).join(Instrument).filter(Instrument.ticker == ticker).order_by(Price.date.desc()).first()
        if not price_rec or not price_rec.close:
            return None
        cur_val = cast(float, price_rec.close) * pos.quantity
        cost = (pos.avg_price or 0) * pos.quantity
        return cur_val - cost
    except Exception:
        return None
    finally:
        db.close()
