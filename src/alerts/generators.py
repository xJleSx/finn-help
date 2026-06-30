from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func

from src.db.models import AlertLog, BondOffering, CorporateEvent, FinancialReport, Instrument, Signal

logger = logging.getLogger(__name__)

ALERT_TYPES = {
    "bond_maturity": "Приближение погашения облигации",
    "report_anomaly": "Аномалия в отчётности",
    "corporate_event": "Корпоративное событие",
    "signal_drop": "Падение уверенности сигнала",
}


def generate_bond_maturity_alerts(db: Any, days_threshold: int = 30) -> list[dict[str, Any]]:
    today = date.today()
    cutoff = today + timedelta(days=days_threshold)
    rows = (
        db.query(BondOffering, Instrument.ticker)
        .join(Instrument, Instrument.id == BondOffering.instrument_id)
        .filter(
            BondOffering.maturity_date.isnot(None),
            BondOffering.maturity_date >= today,
            BondOffering.maturity_date <= cutoff,
        )
        .all()
    )
    alerts = []
    for offering, ticker in rows:
        md = offering.maturity_date
        days_left = (md - today).days if md else 0
        title = f"Погашение {ticker} через {days_left} дн."
        message = (
            f"Облигация {ticker} погашается {md.strftime('%d.%m.%Y')} "
            f"(осталось {days_left} дн.). "
            f"Купон: {offering.coupon_rate or '—'}%, "
            f"YTM: {offering.yield_to_maturity or '—'}%"
        )
        severity = 0.9 if days_left <= 7 else 0.6 if days_left <= 14 else 0.3
        alerts.append({
            "ticker": ticker,
            "alert_type": "bond_maturity",
            "severity": severity,
            "title": title,
            "message": message,
            "user_id": None,
        })
    return alerts


def generate_report_anomalies(db: Any) -> list[dict[str, Any]]:
    today = date.today()
    cutoff = today - timedelta(days=90)
    rows = (
        db.query(FinancialReport, Instrument.ticker)
        .join(Instrument, Instrument.id == FinancialReport.instrument_id)
        .filter(FinancialReport.report_date >= cutoff)
        .order_by(FinancialReport.report_date.desc())
        .all()
    )
    seen: set[int] = set()
    alerts = []
    for report, ticker in rows:
        if report.instrument_id in seen:
            continue
        seen.add(report.instrument_id)
        anomalies = []
        if report.net_profit is not None and report.net_profit < 0:
            anomalies.append("чистый убыток")
        if report.roe is not None and report.roe < 0:
            anomalies.append("отрицательная рентабельность капитала")
        if report.npl_ratio is not None and report.npl_ratio > 15:
            anomalies.append(f"высокая доля просрочки ({report.npl_ratio:.1f}%)")
        if report.capital_adequacy is not None and report.capital_adequacy < 8:
            anomalies.append(f"низкая достаточность капитала ({report.capital_adequacy:.1f}%)")
        if anomalies:
            title = f"Аномалия в отчётности {ticker}"
            message = f"{ticker}: {'; '.join(anomalies)} за период {report.report_date}"
            severity = 0.7 if "чистый убыток" in anomalies else 0.4
            alerts.append({
                "ticker": ticker,
                "alert_type": "report_anomaly",
                "severity": severity,
                "title": title,
                "message": message,
                "user_id": None,
            })
    return alerts


def generate_corporate_event_alerts(db: Any, days_ahead: int = 30) -> list[dict[str, Any]]:
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    rows = (
        db.query(CorporateEvent, Instrument.ticker)
        .join(Instrument, Instrument.id == CorporateEvent.instrument_id)
        .filter(
            CorporateEvent.announcement_date >= today,
            CorporateEvent.announcement_date <= cutoff,
        )
        .order_by(CorporateEvent.announcement_date.asc())
        .all()
    )
    alerts = []
    for event, ticker in rows:
        ad = event.announcement_date
        if event.event_type == "dividend":
            amount = event.dividend_amount
            title = f"Дивиденды {ticker}"
            if amount:
                message = f"{ticker}: {amount:.0f} ₽/акц, дата: {ad.strftime('%d.%m.%Y')}"
            else:
                message = f"{ticker}: дивидендная отсечка {ad.strftime('%d.%m.%Y')}"
            severity = 0.6 if amount and amount > 50 else 0.3
        elif event.event_type == "buyback":
            title = f"Байбэк {ticker}"
            message = f"{ticker}: обратный выкуп акций, объявлен {ad.strftime('%d.%m.%Y')}"
            severity = 0.5
        elif event.event_type == "split":
            title = f"Сплит {ticker}"
            message = f"{ticker}: дробление/консолидация акций {ad.strftime('%d.%m.%Y')}"
            severity = 0.3
        else:
            continue
        alerts.append({
            "ticker": ticker,
            "alert_type": "corporate_event",
            "severity": severity,
            "title": title,
            "message": message,
            "user_id": None,
        })
    return alerts


def generate_signal_drop_alerts(db: Any, drop_threshold: float = 0.2) -> list[dict[str, Any]]:
    yesterday_signals = (
        db.query(Signal, Instrument.ticker)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .filter(func.date(Signal.date) == date.today() - timedelta(days=1))
        .all()
    )
    today_signals = {
        t: s
        for s, t in (
            db.query(Signal, Instrument.ticker)
            .join(Instrument, Instrument.id == Signal.instrument_id)
            .filter(func.date(Signal.date) == date.today())
            .all()
        )
    }
    alerts = []
    for signal, ticker in yesterday_signals:
        today_s = today_signals.get(ticker)
        if not today_s or not today_s.confidence:
            continue
        drop = (signal.confidence or 0) - (today_s.confidence or 0)
        if drop > drop_threshold:
            title = f"Падение уверенности {ticker}"
            conf_from = signal.confidence or 0
            conf_to = today_s.confidence or 0
            message = f"{ticker}: уверенность {conf_from:.0%} → {conf_to:.0%} (падение {drop:.0%})"
            severity = min(drop * 2, 0.9)
            alerts.append({
                "ticker": ticker,
                "alert_type": "signal_drop",
                "severity": severity,
                "title": title,
                "message": message,
                "user_id": None,
            })
    return alerts


def store_alerts(db: Any, alerts: list[dict[str, Any]]) -> int:
    count = 0
    for a in alerts:
        exists = (
            db.query(AlertLog)
            .filter(
                AlertLog.ticker == a["ticker"],
                AlertLog.alert_type == a["alert_type"],
                AlertLog.title == a["title"],
                func.date(AlertLog.created_at) == date.today(),
            )
            .first()
        )
        if exists:
            continue
        try:
            log = AlertLog(
                ticker=a["ticker"],
                alert_type=a["alert_type"],
                severity=float(a["severity"]),
                title=a["title"],
                message=a.get("message", ""),
                read=False,
                user_id=a.get("user_id"),
            )
            db.add(log)
            count += 1
        except Exception as e:
            logger.warning("Failed to store alert: %s", e)
    if count:
        try:
            db.commit()
        except Exception as e:
            logger.error("Alert commit failed: %s", e)
            db.rollback()
            return 0
    return count


def generate_all_alerts(db: Any) -> list[dict[str, Any]]:
    alerts = []
    alerts.extend(generate_bond_maturity_alerts(db))
    alerts.extend(generate_report_anomalies(db))
    alerts.extend(generate_corporate_event_alerts(db))
    alerts.extend(generate_signal_drop_alerts(db))
    return alerts
