"""ResponseFormatter — агрегирует данные из всех enrichment-моделей в готовые блоки."""

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.models import (
    BondOffering,
    CompanyProfile,
    CorporateEvent,
    FinancialReport,
    FundamentalMetric,
    Instrument,
)

logger = logging.getLogger(__name__)


def fmt(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    return f"{val:,}{suffix}".replace(",", " ") if isinstance(val, (int, float)) else str(val)


def fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{val:.1f}%"


def fmt_rub(val: Optional[float]) -> str:
    if val is None:
        return "—"
    suffix = ""
    if abs(val) >= 1e12:
        val /= 1e12
        suffix = " трлн"
    elif abs(val) >= 1e9:
        val /= 1e9
        suffix = " млрд"
    elif abs(val) >= 1e6:
        val /= 1e6
        suffix = " млн"
    return f"{val:,.2f}{suffix} ₽".replace(",", " ")


def load_company_profile(db: Session, instrument_id: int) -> Optional[CompanyProfile]:
    return db.query(CompanyProfile).filter(CompanyProfile.instrument_id == instrument_id).first()


def load_financial_report(db: Session, instrument_id: int) -> Optional[FinancialReport]:
    return (
        db.query(FinancialReport)
        .filter(FinancialReport.instrument_id == instrument_id)
        .order_by(FinancialReport.report_date.desc())
        .first()
    )


def load_bond_offering(db: Session, instrument_id: int) -> Optional[BondOffering]:
    return (
        db.query(BondOffering)
        .filter(BondOffering.instrument_id == instrument_id)
        .order_by(BondOffering.offering_date.desc())
        .first()
    )


def load_upcoming_events(db: Session, instrument_id: int, days: int = 90) -> list[CorporateEvent]:
    cutoff = date.today()
    from datetime import timedelta
    end = date.today() + timedelta(days=days)
    return (
        db.query(CorporateEvent)
        .filter(
            CorporateEvent.instrument_id == instrument_id,
            CorporateEvent.announcement_date >= cutoff,
            CorporateEvent.announcement_date <= end,
        )
        .order_by(CorporateEvent.announcement_date.asc())
        .all()
    )


def load_fundamental_metric(db: Session, instrument_id: int) -> Optional[FundamentalMetric]:
    return (
        db.query(FundamentalMetric)
        .filter(FundamentalMetric.instrument_id == instrument_id)
        .order_by(FundamentalMetric.date.desc())
        .first()
    )


def build_profile_block(profile: Optional[CompanyProfile]) -> str:
    if not profile:
        return ""
    parts = []
    desc = str(profile.description or "")
    if desc:
        parts.append(desc[:300])
    website = profile.website or ""
    if website:
        parts.append(f"Сайт: {website}")
    info = []
    if profile.industry:
        info.append(f"Отрасль: {profile.industry}")
    if profile.employees:
        info.append(f"Сотрудники: {fmt(profile.employees)}")
    if profile.founded_year:
        info.append(f"Основан: {profile.founded_year}")
    if info:
        parts.append(" | ".join(info))
    return "\n".join(parts)


FINANCIAL_FIELDS: list[tuple[str, str, str]] = [
    ("net_profit", "Чистая прибыль", "rub"),
    ("revenue", "Выручка", "rub"),
    ("net_interest_income", "Чистые процентные доходы", "rub"),
    ("operating_income", "Операционные доходы", "rub"),
    ("total_assets", "Активы", "rub"),
    ("total_liabilities", "Обязательства", "rub"),
    ("total_equity", "Собственный капитал", "rub"),
    ("loan_portfolio", "Кредитный портфель", "rub"),
    ("customer_deposits", "Средства клиентов", "rub"),
    ("roe", "ROE", "pct"),
    ("roa", "ROA", "pct"),
    ("net_margin", "Чистая процентная маржа", "pct"),
    ("npl_ratio", "NPL", "pct"),
    ("capital_adequacy", "Достаточность капитала", "pct"),
    ("cost_income_ratio", "CIR", "pct"),
]


def format_financial_facts(data: dict[str, Any]) -> list[str]:
    """Форматирует финансовые факты из словаря (единый источник для всех модулей)."""
    facts = []
    date_raw = data.get("report_date", "")
    date_str = str(date_raw) if date_raw else ""

    prefix = f" ({date_str})" if date_str else ""
    for key, label, kind in FINANCIAL_FIELDS:
        val = data.get(key)
        if val is None:
            continue
        if kind == "rub":
            facts.append(f"{label}{prefix}: {fmt_rub(val)}")
        else:
            facts.append(f"{label}{prefix}: {fmt_pct(val)}")
    return facts


def build_financial_highlights(report: Optional[FinancialReport]) -> list[str]:
    if not report:
        return []
    data = {
        "period_type": report.period_type or "FY",
        "report_date": report.report_date.strftime("%Y-%m-%d") if report.report_date else "",
        "net_profit": report.net_profit,
        "revenue": report.revenue,
        "net_interest_income": report.net_interest_income,
        "operating_income": report.operating_income,
        "total_assets": report.total_assets,
        "total_liabilities": report.total_liabilities,
        "total_equity": report.total_equity,
        "loan_portfolio": report.loan_portfolio,
        "customer_deposits": report.customer_deposits,
        "roe": report.roe,
        "roa": report.roa,
        "net_margin": report.net_margin,
        "npl_ratio": report.npl_ratio,
        "capital_adequacy": report.capital_adequacy,
        "cost_income_ratio": report.cost_income_ratio,
    }
    return format_financial_facts(data)


def build_bond_analysis(offering: Optional[BondOffering]) -> list[str]:
    if not offering:
        return []
    params = []
    if offering.coupon_type and offering.coupon_rate is not None:
        ct = {
            "fixed": "фиксированный",
            "float": "флоатер",
            "floater": "флоатер",
            "zero": "бескупонная",
        }.get(offering.coupon_type.lower(), offering.coupon_type)
        params.append(f"Купон: {ct} {fmt_pct(offering.coupon_rate)}")
    elif offering.coupon_rate is not None:
        params.append(f"Купон: {fmt_pct(offering.coupon_rate)}")
    if offering.yield_to_maturity is not None:
        params.append(f"YTM: {fmt_pct(offering.yield_to_maturity)}")
    if offering.credit_rating:
        params.append(f"Рейтинг: {offering.credit_rating}")
    if offering.maturity_date:
        params.append(f"Погашение: {offering.maturity_date.strftime('%d.%m.%Y')}")
    if offering.coupon_period_days:
        params.append(f"Период купона: {offering.coupon_period_days} дн.")
    if offering.volume is not None:
        params.append(f"Объём: {fmt_rub(offering.volume)}")
    if offering.has_amortization:
        params.append("Амортизация: да")
    if offering.has_offer:
        params.append("Оферта: да")
    if offering.min_lot_rub:
        params.append(f"Мин. заявка: {fmt_rub(offering.min_lot_rub)}")
    if offering.qual_investor_only:
        params.append("Только квал. инвесторы")
    return params


def build_corporate_events_block(events: list[CorporateEvent], max_items: int = 5) -> list[str]:
    if not events:
        return []
    lines = []
    for ev in events[:max_items]:
        emoji = {
            "dividend": "💵",
            "buyback": "🔄",
            "split": "🔀",
            "emission": "📄",
        }.get(ev.event_type, "📌")
        parts = [f"{emoji} {ev.event_type.title()}"]
        if ev.announcement_date:
            parts.append(f"({ev.announcement_date.strftime('%d.%m.%Y')})")
        if ev.dividend_amount is not None:
            parts.append(f"{fmt_rub(ev.dividend_amount)}/акц")
        if ev.status:
            parts.append(f"[{ev.status}]")
        lines.append(" ".join(parts))
    return lines


def build_fundamental_comparison(
    fm: Optional[FundamentalMetric], sector_avg: Optional[dict[str, float]] = None
) -> list[str]:
    if not fm:
        return []
    lines = []
    if fm.market_cap is not None:
        lines.append(f"Капитализация: {fmt_rub(fm.market_cap)}")
    if fm.pe_ratio is not None:
        pe_str = f"P/E: {fmt(fm.pe_ratio)}"
        if sector_avg and sector_avg.get("pe_ratio"):
            diff = (fm.pe_ratio / sector_avg["pe_ratio"] - 1) * 100
            pe_str += f" (vs сектор: {diff:+.0f}%)"
        lines.append(pe_str)
    if fm.pb_ratio is not None:
        pb_str = f"P/B: {fmt(fm.pb_ratio)}"
        if sector_avg and sector_avg.get("pb_ratio"):
            diff = (fm.pb_ratio / sector_avg["pb_ratio"] - 1) * 100
            pb_str += f" (vs сектор: {diff:+.0f}%)"
        lines.append(pb_str)
    if fm.eps is not None:
        lines.append(f"EPS: {fmt_rub(fm.eps)}")
    if fm.roe is not None:
        lines.append(f"ROE: {fmt_pct(fm.roe)}")
    if fm.revenue is not None:
        lines.append(f"Выручка: {fmt_rub(fm.revenue)}")
    if fm.net_income is not None:
        lines.append(f"Чистая прибыль: {fmt_rub(fm.net_income)}")
    return lines


def build_enriched_context_block(db: Session, instrument: Instrument) -> str:
    """Build a ticker context string for LLM prompts."""
    parts = []

    profile = load_company_profile(db, instrument.id)
    if profile:
        pb = build_profile_block(profile)
        if pb:
            parts.append(f"**Профиль компании:**\n{pb}")

    report = load_financial_report(db, instrument.id)
    fh = build_financial_highlights(report)
    if fh:
        parts.append("**Финансовая отчётность:**\n" + "\n".join(fh))

    if instrument.instrument_type == "bond":
        offering = load_bond_offering(db, instrument.id)
        ba = build_bond_analysis(offering)
        if ba:
            parts.append("**Параметры выпуска:**\n" + "\n".join(ba))

    events = load_upcoming_events(db, instrument.id, days=90)
    ce = build_corporate_events_block(events)
    if ce:
        parts.append("**Корпоративные события:**\n" + "\n".join(ce))

    fm = load_fundamental_metric(db, instrument.id)
    fc = build_fundamental_comparison(fm)
    if fc:
        parts.append("**Фундаментальные метрики:**\n" + "\n".join(fc))

    return "\n\n".join(parts)
