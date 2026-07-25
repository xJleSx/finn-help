from __future__ import annotations

import contextlib
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from src.db.models import BondCouponSchedule, BondOffering, Instrument

logger = structlog.get_logger(__name__)

_RATING_MAP: dict[str, int] = {
    "AAA": 7,
    "AA+": 6,
    "AA": 5,
    "AA-": 4,
    "A+": 3,
    "A": 2,
    "A-": 1,
    "BBB+": 0,
    "BBB": -1,
    "BBB-": -2,
    "BB+": -3,
    "BB": -4,
    "BB-": -5,
    "B+": -6,
    "B": -7,
    "B-": -8,
}


def _rating_score(rating: str | None) -> int:
    if not rating:
        return -999
    return _RATING_MAP.get(rating.upper().strip(), -999)


def _paid_coupon_count(schedule_rows: list[BondCouponSchedule]) -> int:
    """Count how many coupons have been paid (date in the past or paid flag set)."""
    today = date.today()
    count = 0
    for row in schedule_rows:
        if row.coupon_number is not None and row.coupon_number <= 0:
            continue
        if row.paid is True or row.coupon_date <= today:
            count += 1
    return count


def _is_recently_issued(schedule_rows: list[BondCouponSchedule]) -> bool:
    """Bond is considered new if 2 or fewer coupons have been paid."""
    return _paid_coupon_count(schedule_rows) <= 2


async def discover_new_bonds(
    db: AsyncSession,
    min_ytm: float | None = None,
    max_results: int = 20,
    min_days_to_first_coupon: int = 0,
    max_age_days: int = 90,
) -> list[dict[str, Any]]:
    """Fetch recently issued bonds from MOEX, add new ones to DB, return ranked list.

    Only processes bonds issued within the last ``max_age_days`` days to avoid
    bulk-importing the entire MOEX bond universe.
    """
    from src.collectors.bonds import BondOfferingCollector
    from src.collectors.moex import MOEXCollector

    moex = MOEXCollector()
    await moex.__aenter__()
    try:
        bonds_list = await moex.get_bonds(columns=["SECID", "SHORTNAME", "ISSUEDATE"])
    finally:
        await moex.__aexit__(None, None, None)

    cutoff = date.today() - timedelta(days=max_age_days)

    moex_tickers: dict[str, dict[str, Any]] = {}
    for b in bonds_list:
        secid = b.get("SECID") or b.get("secid")
        if not secid:
            continue
        raw_date = b.get("ISSUEDATE") or b.get("issue_date")
        issue_date = _parse_coupon_date(raw_date) if raw_date else None
        if issue_date is None or issue_date < cutoff:
            continue
        moex_tickers[secid] = b

    if not moex_tickers:
        logger.info("discover_new_bonds: no recently issued bonds found on MOEX")
        from src.db.connection import get_session
        with get_session() as sync_db:
            return find_new_bonds(sync_db, min_ytm, max_results, min_days_to_first_coupon)

    result = await db.execute(select(Instrument.ticker).filter(Instrument.instrument_type == "bond"))
    existing_tickers = {row[0] for row in result.fetchall()}

    new_tickers = set(moex_tickers.keys()) - existing_tickers
    if not new_tickers:
        logger.info("discover_new_bonds: no new bonds found (all recent ones already in DB)")
        from src.db.connection import get_session
        with get_session() as sync_db:
            return find_new_bonds(sync_db, min_ytm, max_results, min_days_to_first_coupon)

    logger.info("discover_new_bonds: %d new bonds to add (issued within %d days)", len(new_tickers), max_age_days)

    collector = BondOfferingCollector()
    await collector.__aenter__()
    added = 0
    failed = 0
    try:
        for ticker in sorted(new_tickers):
            try:
                data = await collector.fetch_by_ticker(ticker)
                if not data or not data.get("isin"):
                    failed += 1
                    continue

                inst = Instrument(
                    ticker=ticker,
                    full_name=data.get("full_name", data.get("short_name", ticker)) or ticker,
                    isin=data.get("isin"),
                    instrument_type="bond",
                    lot_size=1,
                    nominal=data.get("nominal_price"),
                )
                db.add(inst)
                await db.flush()

                offering_date = data.get("offering_date")
                if not offering_date:
                    failed += 1
                    await db.rollback()
                    continue

                extra = {}
                if data.get("emitter_id") is not None:
                    extra["emitter_id"] = data["emitter_id"]
                if data.get("company_name"):
                    extra["company_name"] = data["company_name"]

                offering = BondOffering(
                    instrument_id=inst.id,
                    offering_date=offering_date,
                    isin=data.get("isin"),
                    coupon_type=data.get("coupon_type", "fixed"),
                    coupon_rate=data.get("coupon_rate"),
                    coupon_period_days=data.get("coupon_period_days"),
                    yield_to_maturity=data.get("yield_to_maturity"),
                    maturity_date=data.get("maturity_date"),
                    maturity_years=(data["maturity_date"] - date.today()).days / 365.25 if data.get("maturity_date") else None,
                    credit_rating=data.get("credit_rating"),
                    volume=data.get("volume"),
                    has_amortization=data.get("has_amortization", False),
                    has_offer=data.get("has_offer", False),
                    min_lot_rub=data.get("min_lot_rub"),
                    qual_investor_only=data.get("qual_investor_only", False),
                    nominal_price=data.get("nominal_price"),
                    current_price_pct=data.get("current_price_pct"),
                    duration_years=data.get("duration_years"),
                    extra=extra or None,
                )
                db.add(offering)

                coupon_schedule = data.get("coupon_schedule", [])
                for cpn in coupon_schedule:
                    cpn_date = _parse_coupon_date(cpn.get("coupondate") or cpn.get("couponDate"))
                    if not cpn_date:
                        continue
                    with contextlib.suppress(ValueError, TypeError):
                        value = float(cpn.get("value", 0))
                    schedule_entry = BondCouponSchedule(
                        instrument_id=inst.id,
                        coupon_date=cpn_date,
                        coupon_value=value,
                        coupon_number=_safe_int(cpn.get("couponnumber") or cpn.get("couponNumber")),
                        currency=cpn.get("currency", "RUB"),
                        fix_date=_parse_coupon_date(cpn.get("fixdate") or cpn.get("fixDate")),
                        face_value=_safe_float(cpn.get("facevalue") or cpn.get("faceValue")),
                        initial_face_value=_safe_float(cpn.get("initialfacevalue") or cpn.get("initialFaceValue")),
                    )
                    db.add(schedule_entry)

                await db.flush()
                added += 1
            except Exception as e:
                logger.warning("Failed to add bond %s: %s", ticker, e)
                failed += 1
                continue

        await db.commit()
        logger.info("discover_new_bonds: added %d, failed %d", added, failed)
    finally:
        await collector.__aexit__(None, None, None)

    from src.db.connection import get_session
    with get_session() as sync_db:
        return find_new_bonds(sync_db, min_ytm, max_results, min_days_to_first_coupon)


def find_new_bonds(
    db: Session,
    min_ytm: float | None = None,
    max_results: int = 20,
    min_days_to_first_coupon: int = 0,
    available_tickers: set[str] | None = None,
) -> list[dict[str, Any]]:
    instruments = (
        db.query(Instrument)
        .options(joinedload(Instrument.bond_offerings), joinedload(Instrument.coupon_schedule))
        .filter(Instrument.instrument_type == "bond")
        .all()
    )

    result: list[dict[str, Any]] = []
    today = date.today()

    for inst in instruments:
        if not inst.bond_offerings:
            continue

        if available_tickers is not None and inst.ticker not in available_tickers:
            continue

        offering = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)[0]
        schedule_rows: list[BondCouponSchedule] = inst.coupon_schedule or []

        if not _is_recently_issued(schedule_rows):
            continue

        if min_ytm is not None and (offering.yield_to_maturity is None or offering.yield_to_maturity < min_ytm):
            continue

        first_coupon_date = None
        if schedule_rows:
            future_coupons = [r for r in schedule_rows if r.coupon_date > today]
            if future_coupons:
                first_coupon_date = min(r.coupon_date for r in future_coupons)

        days_to_first = (first_coupon_date - today).days if first_coupon_date else None

        if min_days_to_first_coupon > 0 and (days_to_first is None or days_to_first < min_days_to_first_coupon):
            continue

        rating = offering.credit_rating
        rating_score = _rating_score(rating)

        extra = offering.extra or {}
        company_name = extra.get("company_name", "")
        if not company_name:
            raw = inst.full_name or offering.isin or inst.ticker
            company_name = _extract_company_name(raw)

        result.append(
            {
                "ticker": inst.ticker,
                "short_name": (inst.full_name or inst.ticker)[:40],
                "isin": offering.isin or inst.isin or "",
                "company_name": company_name,
                "coupon_rate": offering.coupon_rate,
                "coupon_type": offering.coupon_type,
                "coupon_period_days": offering.coupon_period_days,
                "yield_to_maturity": offering.yield_to_maturity,
                "credit_rating": rating or "—",
                "rating_score": rating_score,
                "current_price_pct": offering.current_price_pct,
                "first_coupon_date": first_coupon_date.isoformat() if first_coupon_date else None,
                "days_to_first_coupon": days_to_first,
                "maturity_date": offering.maturity_date.isoformat() if offering.maturity_date else None,
                "offering_date": offering.offering_date.isoformat() if offering.offering_date else None,
                "nominal_price": offering.nominal_price,
                "has_amortization": offering.has_amortization,
                "has_offer": offering.has_offer,
                "data_incomplete": not bool(schedule_rows),
            }
        )

    result.sort(key=lambda b: (-b["rating_score"], -(b["yield_to_maturity"] or 0), b["days_to_first_coupon"] or 9999))

    return result[:max_results]


def _parse_coupon_date(val: Any) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except (ValueError, TypeError):
            pass
    return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return int(val)
    return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return float(val)
    return None


def _extract_company_name(raw: str) -> str:
    """Heuristic: extract issuer name from bond name by stripping series suffix."""
    import re
    name = raw.strip()
    if not name:
        return ""
    # Strip series like 001P, 003P-02, 2P-13, БО-01, etc.
    name = re.sub(r"\s+(?:\d+(?:[PpРр][-\d]*|[-\d]*)|[A-Za-zА-Яа-я]*\d+[PpРр]?[-\d]*)$", "", name)
    # Strip common bond-type words
    name = re.sub(r"\s+(облигация|биржевая|БО|exchange|bond|серия|выпуск).*", "", name, flags=re.IGNORECASE)
    # If result is empty or unchanged, try first space-delimited word
    if not name or name == raw:
        parts = (name if name else raw).split()
        name = parts[0] if parts else raw
    return name[:30]
