import logging
from dataclasses import dataclass
from typing import Any, Optional, cast

from src.db.connection import get_session
from src.db.models import BondOffering, Instrument, Price
from src.interfaces.telegram_helpers import get_portfolio_positions, html_escape

logger = logging.getLogger(__name__)

DEPOSIT_RATE = 0.06


@dataclass
class BenchmarkComparison:
    portfolio_return_pct: float
    bond_index_return_pct: float
    rgbir_return_pct: float
    deposit_return_pct: float
    alpha_pct: float
    reason: str
    period_label: str


def compare_benchmarks(period_days: int = 7) -> Optional[BenchmarkComparison]:
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            return None
        portfolio_ret = _portfolio_return(rows, period_days)
        bond_index_ret = _index_return("RGBITR", period_days)
        rgbir_ret = _index_return("RGBI", period_days)
        deposit_ret = (1 + DEPOSIT_RATE) ** (period_days / 365) - 1
        alpha = portfolio_ret - bond_index_ret
        reason = _explain_performance(rows, period_days)
        from datetime import date as dt_date
        today = dt_date.today()
        period_label = "неделя {}".format(today.isocalendar()[1])
        return BenchmarkComparison(
            portfolio_return_pct=portfolio_ret,
            bond_index_return_pct=bond_index_ret,
            rgbir_return_pct=rgbir_ret,
            deposit_return_pct=deposit_ret,
            alpha_pct=alpha,
            reason=reason,
            period_label=period_label,
        )
    except Exception:
        logger.exception("benchmark_comparison_error")
        return None
    finally:
        db.close()


def _portfolio_return(rows: list[dict[str, Any]], period_days: int) -> float:
    total_current = sum(r["value"] for r in rows)
    if total_current <= 0:
        return 0.0
    db = get_session()
    try:
        total_prev = 0.0
        for r in rows:
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(period_days + 2)
                .all()
            )
            if len(prices) > period_days and prices[-1].close:
                prev = cast(float, prices[-1].close)
                total_prev += prev * r["quantity"]
        if total_prev <= 0:
            return 0.0
        return (total_current - total_prev) / total_prev
    finally:
        db.close()


def _index_return(ticker: str, period_days: int) -> float:
    db = get_session()
    try:
        prices = (
            db.query(Price)
            .join(Instrument)
            .filter(Instrument.ticker == ticker)
            .order_by(Price.date.desc())
            .limit(period_days + 2)
            .all()
        )
        if len(prices) > period_days and prices[0].close and prices[-1].close:
            return (cast(float, prices[0].close) - cast(float, prices[-1].close)) / cast(float, prices[-1].close)
        return 0.0
    finally:
        db.close()


def _explain_performance(rows: list[dict[str, Any]], period_days: int) -> str:
    reasons = []
    db = get_session()
    try:
        for r in rows:
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(period_days + 2)
                .all()
            )
            if len(prices) > period_days and prices[0].close and prices[-1].close:
                ret = (cast(float, prices[0].close) - cast(float, prices[-1].close)) / cast(float, prices[-1].close)
                if ret > 0.03:
                    inst = db.query(Instrument).filter_by(ticker=r["ticker"]).first()
                    ytm_val = 0.0
                    if inst:
                        offering = db.query(BondOffering).filter_by(instrument_id=inst.id).order_by(BondOffering.offering_date.desc()).first()
                        if offering:
                            ytm_val = float(offering.yield_to_maturity or 0)
                    reasons.append("{} (+{:.1%}, YTM {:.1%})".format(html_escape(r["ticker"]), ret, ytm_val * 100))
    finally:
        db.close()
    if reasons:
        return "Причина: " + ", ".join(reasons[:3])
    return "Диверсификация портфеля"


def format_benchmark_comparison(cmp: BenchmarkComparison) -> str:
    lines = [
        "📈 <b>Сравнение с рынком ({})</b>\n".format(cmp.period_label),
        "Твой портфель: {:+.2%}".format(cmp.portfolio_return_pct),
        "Индекс МосБиржи облигаций: {:+.2%}".format(cmp.bond_index_return_pct),
        "Индекс RGBI (гос. облигации): {:+.2%}".format(cmp.rgbir_return_pct),
        "Депозит ({:.0f}% годовых): {:+.2%}".format(DEPOSIT_RATE * 100, cmp.deposit_return_pct),
        "",
    ]
    if cmp.alpha_pct > 0:
        lines.append("🏆 Ты обгоняешь рынок на {:+.2%}".format(cmp.alpha_pct))
    else:
        lines.append("📉 Ты отстаёшь от рынка на {:+.2%}".format(cmp.alpha_pct))
    lines.append("")
    if cmp.reason:
        lines.append(cmp.reason)
    return "\n".join(lines)
