from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import BondCouponSchedule, BondOffering, Instrument, Price
from src.interfaces.api.auth import get_db
from src.interfaces.api.schemas import (
    BondAIAnalysisResponse,
    BondAnalysisResponse,
    BondCashFlowResponse,
    BondDetailResponse,
    BondMetricsResponse,
    BondPriceHistoryResponse,
    CouponPaymentResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["bonds"])


@router.get("/api/bonds")
async def list_bonds(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Instrument)
        .options(selectinload(Instrument.bond_offerings))
        .where(Instrument.instrument_type == "bond")
        .order_by(Instrument.ticker)
    )
    instruments = result.scalars().all()

    output: list[dict[str, Any]] = []
    for inst in instruments:
        offering = None
        if inst.bond_offerings:
            sorted_offerings = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)
            offering = sorted_offerings[0]

        nominal = (offering.nominal_price or inst.nominal or 1000) if offering else 1000
        price_pct = offering.current_price_pct if offering else 100.0
        market_price = round(nominal * price_pct / 100.0, 2)

        coupon_frequency = "SemiAnnual"
        if offering and offering.coupon_period_days:
            if offering.coupon_period_days <= 35:
                coupon_frequency = "Monthly"
            elif offering.coupon_period_days <= 95:
                coupon_frequency = "Quarterly"
            elif offering.coupon_period_days <= 200:
                coupon_frequency = "SemiAnnual"
            else:
                coupon_frequency = "Annual"

        entry: dict[str, Any] = {
            "id": str(inst.id),
            "ticker": inst.ticker,
            "isin": offering.isin if offering else (inst.isin or ""),
            "name": inst.full_name or inst.ticker,
            "issuer": inst.full_name or "",
            "currentPrice": market_price,
            "purchasePrice": market_price,
            "nominal": nominal,
            "couponValue": 0,
            "couponYield": round(offering.coupon_rate, 2) if offering and offering.coupon_rate else 0,
            "yieldToMaturity": round(offering.yield_to_maturity, 2) if offering and offering.yield_to_maturity else 0,
            "duration": round(offering.duration_years, 2) if offering and offering.duration_years else 0,
            "rating": (offering.credit_rating or "NR") if offering else "NR",
            "couponFrequency": coupon_frequency,
            "nextCouponDate": "",
            "maturityDate": offering.maturity_date.isoformat() if offering and offering.maturity_date else "",
            "quantity": 0,
            "invested": 0,
            "currentValue": 0,
            "expectedRedemptionValue": 0,
            "unrealizedPnL": 0,
            "aiScore": 50,
        }

        if offering and offering.coupon_period_days and offering.coupon_rate:
            coupon_amount = round(nominal * offering.coupon_rate / 100 * offering.coupon_period_days / 365, 2)
            entry["couponValue"] = coupon_amount

        price_result = await db.execute(
            select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
        )
        last_price = price_result.scalar_one_or_none()
        if last_price and last_price.close:
            entry["currentPrice"] = round(float(last_price.close), 2)

        output.append(entry)

    return output


@router.get("/api/bonds/{ticker}")
async def get_bond(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(Instrument)
        .options(selectinload(Instrument.bond_offerings))
        .where(Instrument.ticker == ticker.upper(), Instrument.instrument_type == "bond")
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Bond not found")

    offering = None
    if inst.bond_offerings:
        sorted_offerings = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)
        offering = sorted_offerings[0]

    nominal = (offering.nominal_price or inst.nominal or 1000) if offering else 1000
    price_pct = offering.current_price_pct if offering else 100.0
    market_price = round(nominal * price_pct / 100.0, 2)

    coupon_frequency = "SemiAnnual"
    if offering and offering.coupon_period_days:
        if offering.coupon_period_days <= 35:
            coupon_frequency = "Monthly"
        elif offering.coupon_period_days <= 95:
            coupon_frequency = "Quarterly"
        elif offering.coupon_period_days <= 200:
            coupon_frequency = "SemiAnnual"
        else:
            coupon_frequency = "Annual"

    entry: dict[str, Any] = {
        "id": str(inst.id),
        "ticker": inst.ticker,
        "isin": offering.isin if offering else (inst.isin or ""),
        "name": inst.full_name or inst.ticker,
        "issuer": inst.full_name or "",
        "currentPrice": market_price,
        "purchasePrice": market_price,
        "nominal": nominal,
        "couponValue": 0,
        "couponYield": round(offering.coupon_rate, 2) if offering and offering.coupon_rate else 0,
        "yieldToMaturity": round(offering.yield_to_maturity, 2) if offering and offering.yield_to_maturity else 0,
        "duration": round(offering.duration_years, 2) if offering and offering.duration_years else 0,
        "rating": (offering.credit_rating or "NR") if offering else "NR",
        "couponFrequency": coupon_frequency,
        "nextCouponDate": "",
        "maturityDate": offering.maturity_date.isoformat() if offering and offering.maturity_date else "",
        "quantity": 0,
        "invested": 0,
        "currentValue": 0,
        "expectedRedemptionValue": 0,
        "unrealizedPnL": 0,
        "aiScore": 50,
    }

    if offering and offering.coupon_period_days and offering.coupon_rate:
        coupon_amount = round(nominal * offering.coupon_rate / 100 * offering.coupon_period_days / 365, 2)
        entry["couponValue"] = coupon_amount

    price_result = await db.execute(
        select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
    )
    last_price = price_result.scalar_one_or_none()
    if last_price and last_price.close:
        entry["currentPrice"] = round(float(last_price.close), 2)

    return entry


async def _resolve_bond(db: AsyncSession, ticker: str) -> tuple[Instrument, BondOffering]:
    result = await db.execute(
        select(Instrument)
        .options(selectinload(Instrument.bond_offerings))
        .where(Instrument.ticker == ticker.upper())
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(404, "Bond not found")

    offering = None
    if inst.bond_offerings:
        sorted_offerings = sorted(inst.bond_offerings, key=lambda o: o.offering_date or date.min, reverse=True)
        offering = sorted_offerings[0]

    if not offering:
        raise HTTPException(404, "Bond offering data not found")

    return inst, offering


@router.get("/api/instruments/{ticker}/details", response_model=BondDetailResponse)
async def get_bond_details(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    issuer = inst.full_name or ""
    if offering.credit_rating:
        issuer = f"{inst.full_name or ''} ({offering.credit_rating})"

    return {
        "issuer": issuer.strip(),
        "isin": offering.isin or inst.isin or "",
        "ticker": inst.ticker,
        "currency": inst.currency or "RUB",
        "nominal": offering.nominal_price or inst.nominal or 1000,
        "couponRate": offering.coupon_rate or 0,
        "issueDate": offering.offering_date.isoformat() if offering.offering_date else "",
        "maturityDate": offering.maturity_date.isoformat() if offering.maturity_date else "",
        "offerDate": None,
        "amortization": offering.has_amortization or False,
    }


@router.get("/api/instruments/{ticker}/metrics", response_model=BondMetricsResponse)
async def get_bond_metrics(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    nominal = offering.nominal_price or inst.nominal or 1000
    current_price_pct = offering.current_price_pct or 100.0
    market_price = nominal * current_price_pct / 100.0

    duration = offering.duration_years
    modified_duration = duration * 0.95 if duration else None

    result = await db.execute(
        select(Price).where(Price.instrument_id == inst.id).order_by(Price.date.desc()).limit(1)
    )
    last_price_row = result.scalar_one_or_none()

    return {
        "yieldToMaturity": offering.yield_to_maturity,
        "currentYield": offering.coupon_rate,
        "duration": round(duration, 2) if duration else None,
        "modifiedDuration": round(modified_duration, 2) if modified_duration else None,
        "coupon": None,
        "accruedInterest": None,
        "purchasePrice": None,
        "marketPrice": round(market_price, 2) if market_price else None,
        "profit": None,
        "fairValue": round(market_price * 1.025, 2) if market_price else None,
    }


@router.get("/api/instruments/{ticker}/analysis", response_model=BondAnalysisResponse)
async def get_bond_analysis(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    pros: list[str] = []
    cons: list[str] = []
    risks: list[str] = []
    score = 50.0
    verdict = "hold"
    allocation = 0

    if offering.yield_to_maturity and offering.coupon_rate:
        spread = offering.yield_to_maturity - offering.coupon_rate
        if spread > 1:
            pros.append(f"YTM ({offering.yield_to_maturity:.1f}%) выше купона ({offering.coupon_rate:.1f}%)")
            score += 10
        elif spread < -1:
            cons.append(f"YTM ({offering.yield_to_maturity:.1f}%) ниже купона ({offering.coupon_rate:.1f}%)")
            score -= 5

    if offering.credit_rating:
        rating = offering.credit_rating.upper()
        if rating in ("AAA", "AA+"):
            pros.append(f"Высокий кредитный рейтинг: {offering.credit_rating}")
            score += 15
            allocation = 25
        elif rating in ("AA", "AA-"):
            pros.append(f"Хороший кредитный рейтинг: {offering.credit_rating}")
            score += 10
            allocation = 20
        elif rating in ("A+", "A", "A-"):
            allocation = 15
            score += 5
        elif rating.startswith("BBB"):
            risks.append(f"Средний кредитный рейтинг: {offering.credit_rating}")
            allocation = 10
        else:
            risks.append(f"Низкий кредитный рейтинг: {offering.credit_rating}")
            score -= 10
            allocation = 5
    else:
        risks.append("Нет данных о кредитном рейтинге")

    if offering.yield_to_maturity:
        if offering.yield_to_maturity > 15:
            pros.append(f"Высокая доходность: {offering.yield_to_maturity:.1f}%")
            score += 10
        elif offering.yield_to_maturity < 5:
            cons.append(f"Низкая доходность: {offering.yield_to_maturity:.1f}%")
            score -= 5

    if offering.duration_years:
        if offering.duration_years > 5:
            risks.append(f"Большая дюрация ({offering.duration_years:.1f} лет) — высокий процентный риск")
            score -= 5
        elif offering.duration_years < 2:
            pros.append(f"Короткая дюрация ({offering.duration_years:.1f} года) — низкий процентный риск")
            score += 5

    if offering.has_amortization:
        pros.append("Амортизация — частичное досрочное погашение")
        score += 5

    risks.append("Изменение ключевой ставки ЦБ")
    risks.append("Инфляционные риски")

    score = max(10, min(95, score))
    if score >= 75:
        verdict = "strong_buy" if score >= 85 else "buy"
    elif score >= 50:
        verdict = "hold"
    elif score >= 30:
        verdict = "reduce"
    else:
        verdict = "sell"

    return {
        "score": score,
        "verdict": verdict,
        "pros": pros,
        "cons": cons,
        "risks": risks,
        "allocation": allocation,
        "updatedAt": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/api/instruments/{ticker}/ai-analysis", response_model=BondAIAnalysisResponse)
async def get_bond_ai_analysis(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    name = inst.full_name or ticker
    rating_str = f" с рейтингом {offering.credit_rating}" if offering.credit_rating else ""
    coupon_str = f"Фиксированный купон {offering.coupon_rate:.1f}%" if offering.coupon_rate else "Купонный доход"

    summary = f"{name}{rating_str} — {coupon_str}. "
    if offering.maturity_date:
        years_remaining = (offering.maturity_date - date.today()).days / 365.25
        summary += f"Погашение через {years_remaining:.1f} лет. "
    if offering.yield_to_maturity:
        summary += f"Доходность к погашению: {offering.yield_to_maturity:.1f}%."
    summary += f" Эмитент — {inst.full_name or 'не указан'}."

    strengths = ["Ликвидный инструмент на Московской бирже"]
    weaknesses: list[str] = []
    risks_list = [
        "Изменение ключевой ставки ЦБ",
        "Инфляционные риски",
    ]

    if offering.credit_rating:
        rating = offering.credit_rating.upper()
        if rating in ("AAA", "AA+"):
            strengths.append("Высокая кредитоспособность")
        elif rating.startswith("A"):
            strengths.append("Хорошая кредитоспособность")
        elif rating.startswith("BBB"):
            weaknesses.append("Средняя кредитоспособность")
        else:
            risks_list.append("Низкая кредитоспособность")

    if offering.duration_years and offering.duration_years > 5:
        risks_list.append(f"Чувствительность к изменению ставок (дюрация {offering.duration_years:.1f} лет)")

    if offering.yield_to_maturity and offering.coupon_rate:
        if offering.yield_to_maturity > offering.coupon_rate:
            strengths.append("Доходность выше купонной — дисконтная облигация")
        else:
            weaknesses.append("Доходность ниже купонной — премиальная облигация")

    recommendation = "Покупать" if (offering.yield_to_maturity or 0) > 10 else "Держать" if (offering.yield_to_maturity or 0) > 5 else "Продавать"
    horizon = "3–5 лет" if (offering.duration_years or 0) > 3 else "1–3 года"
    confidence = min(70 + (15 if offering.credit_rating else 0) + (10 if offering.yield_to_maturity else 0), 95)

    return {
        "summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "risks": risks_list,
        "recommendation": recommendation,
        "investmentHorizon": horizon,
        "confidence": confidence,
    }


@router.get("/api/instruments/{ticker}/price-history", response_model=BondPriceHistoryResponse)
async def get_bond_price_history(
    ticker: str,
    range: str = Query("1M"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    range_days = {
        "1D": 1, "5D": 5, "1M": 30, "3M": 90,
        "6M": 180, "1Y": 365, "3Y": 1095, "5Y": 1825,
    }
    days = range_days.get(range, 30)
    cutoff = date.today() - timedelta(days=days)

    result = await db.execute(
        select(Price)
        .where(Price.instrument_id == inst.id, Price.date >= cutoff)
        .order_by(Price.date)
    )
    prices = result.scalars().all()

    if prices:
        nominal = offering.nominal_price or inst.nominal or 1000
        price_data = [
            {"time": p.date.isoformat(), "value": round(float(p.close) if p.close else 0, 2)}
            for p in prices if p.close
        ]
        volume_data = [
            {"time": p.date.isoformat(), "value": int(p.volume) if p.volume else 0}
            for p in prices if p.volume
        ]
    else:
        price_data = []
        volume_data = []

    return {"price": price_data, "volume": volume_data}


@router.get("/api/instruments/{ticker}/coupons", response_model=list[CouponPaymentResponse])
async def get_bond_coupons(ticker: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    inst, offering = await _resolve_bond(db, ticker)

    schedule_result = await db.execute(
        select(BondCouponSchedule)
        .where(BondCouponSchedule.instrument_id == inst.id)
        .order_by(BondCouponSchedule.coupon_date)
    )
    schedule_rows = schedule_result.scalars().all()

    if schedule_rows:
        today = date.today()
        coupons: list[dict[str, Any]] = []
        for idx, sch in enumerate(schedule_rows):
            if sch.coupon_date < today:
                status = "paid"
            elif sch.coupon_date < today + timedelta(days=365):
                status = "pending"
            else:
                status = "forecast"

            coupons.append({
                "id": f"{ticker}-cpn-{idx}",
                "date": sch.coupon_date.isoformat(),
                "amount": sch.coupon_value,
                "status": status,
            })
            if idx > 48:
                break

        # Also add redemption coupon if maturity_date exists
        if offering.maturity_date:
            coupons.append({
                "id": f"{ticker}-cpn-red",
                "date": offering.maturity_date.isoformat(),
                "amount": (offering.nominal_price or inst.nominal or 1000),
                "status": "forecast" if offering.maturity_date > today else "paid",
            })

        return coupons

    # Fallback to approximate calculation when no schedule
    if not offering.coupon_period_days or not offering.maturity_date:
        return []

    today = date.today()
    maturity = offering.maturity_date
    period = offering.coupon_period_days
    nominal = offering.nominal_price or inst.nominal or 1000
    coupon_rate = offering.coupon_rate or 0
    coupon_amount = round(nominal * coupon_rate / 100 * period / 365, 2)

    if coupon_amount <= 0:
        return []

    coupons: list[dict[str, Any]] = []
    current = maturity
    idx = 0

    while current > today - timedelta(days=period * 12):
        if idx > 24:
            break
        if current < today:
            status = "paid"
        elif current < today + timedelta(days=180):
            status = "pending"
        else:
            status = "forecast"

        coupons.append({
            "id": f"{ticker}-cpn-{idx}",
            "date": current.isoformat(),
            "amount": coupon_amount,
            "status": status,
        })
        current -= timedelta(days=period)
        idx += 1

    coupons.reverse()
    return coupons


@router.get("/api/instruments/{ticker}/cash-flow", response_model=BondCashFlowResponse)
async def get_bond_cash_flow(ticker: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst, offering = await _resolve_bond(db, ticker)

    today = date.today()
    maturity = offering.maturity_date
    if not maturity:
        return {"items": [], "summary": {"totalPayments": 0, "remainingCoupons": 0, "totalCashFlow": 0, "averageCoupon": 0, "maturityDate": ""}}

    nominal = offering.nominal_price or inst.nominal or 1000
    items: list[dict[str, Any]] = []

    schedule_result = await db.execute(
        select(BondCouponSchedule)
        .where(BondCouponSchedule.instrument_id == inst.id)
        .order_by(BondCouponSchedule.coupon_date)
    )
    schedule_rows = schedule_result.scalars().all()

    if schedule_rows:
        for idx, sch in enumerate(schedule_rows):
            if sch.coupon_date < today:
                cf_status = "paid"
            elif sch.coupon_date < today + timedelta(days=365):
                cf_status = "expected"
            else:
                cf_status = "forecast"

            cf_type = "amortization" if sch.is_amortization else "coupon"
            items.append({
                "id": f"{ticker}-cf-{idx}",
                "date": sch.coupon_date.isoformat(),
                "amount": sch.coupon_value or 0,
                "type": cf_type,
                "status": cf_status,
            })

        redemption_item = {
            "id": f"{ticker}-cf-red",
            "date": maturity.isoformat(),
            "amount": nominal,
            "type": "redemption",
            "status": "forecast" if maturity > today else "paid",
        }
        items.append(redemption_item)

        remaining = [i for i in items if i["type"] in ("coupon", "amortization") and i["status"] != "paid"]
        total = round(sum(i["amount"] for i in items), 2)
        coupon_amounts = [i["amount"] for i in items if i["type"] == "coupon" and i["amount"] > 0]
        avg_coupon = round(sum(coupon_amounts) / len(coupon_amounts), 2) if coupon_amounts else 0

        return {
            "items": items,
            "summary": {
                "totalPayments": len(items),
                "remainingCoupons": len(remaining),
                "totalCashFlow": total,
                "averageCoupon": avg_coupon,
                "maturityDate": maturity.isoformat(),
            },
        }

    period = offering.coupon_period_days or 182
    coupon_rate = offering.coupon_rate or 0
    coupon_amount = round(nominal * coupon_rate / 100 * period / 365, 2)

    current = maturity
    idx = 0
    while current > today - timedelta(days=period * 24):
        if idx > 48:
            break
        if current < today:
            cf_status = "paid"
        elif current < today + timedelta(days=365):
            cf_status = "expected"
        else:
            cf_status = "forecast"

        items.append({
            "id": f"{ticker}-cf-cpn-{idx}",
            "date": current.isoformat(),
            "amount": coupon_amount,
            "type": "coupon",
            "status": cf_status,
        })
        current -= timedelta(days=period)
        idx += 1

    items.reverse()

    if offering.has_amortization:
        amort_items = [i for i in items if i["type"] == "coupon"]
        if amort_items:
            amort_per_payment = round(nominal / len(amort_items), 2)
            for i in amort_items:
                i["type"] = "amortization"
                i["amount"] = round((coupon_amount or 0) + amort_per_payment, 2)
                i["id"] = i["id"].replace("cpn", "amort")

    redemption_item = {
        "id": f"{ticker}-cf-red",
        "date": maturity.isoformat(),
        "amount": nominal + (coupon_amount or 0),
        "type": "redemption",
        "status": "forecast" if maturity > today else "paid",
    }
    items.append(redemption_item)

    remaining = [i for i in items if i["type"] in ("coupon", "amortization") and i["status"] != "paid"]
    total = round(sum(i["amount"] for i in items), 2)
    coupon_amounts = [i["amount"] for i in items if i["type"] == "coupon" and i["amount"] > 0]
    avg_coupon = round(sum(coupon_amounts) / len(coupon_amounts), 2) if coupon_amounts else coupon_amount

    return {
        "items": items,
        "summary": {
            "totalPayments": len(items),
            "remainingCoupons": len(remaining),
            "totalCashFlow": total,
            "averageCoupon": avg_coupon,
            "maturityDate": maturity.isoformat(),
        },
    }
