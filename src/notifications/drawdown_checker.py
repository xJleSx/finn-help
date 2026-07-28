import logging
from dataclasses import dataclass
from typing import Any, Optional, cast

from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.interfaces.telegram_helpers import get_portfolio_positions, html_escape

logger = logging.getLogger(__name__)

DRAWDOWN_THRESHOLD = -0.05


@dataclass
class DrawdownAlert:
    current_dd: float
    reason: str
    affected_positions: list[dict[str, Any]]
    is_market_risk: bool
    recommendation: str


def check_drawdown(threshold: float = DRAWDOWN_THRESHOLD) -> Optional[DrawdownAlert]:
    db = get_session()
    try:
        rows = get_portfolio_positions(db)
        if not rows:
            return None
        total_hist = _build_portfolio_history(rows)
        if len(total_hist) < 20:
            return None
        from src.analysis.metrics import compute_max_drawdown
        mdd = compute_max_drawdown(total_hist)
        if mdd >= threshold:
            return None
        current_from_peak = (total_hist[-1] / max(total_hist)) - 1
        affected = []
        for r in rows:
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(5)
                .all()
            )
            if len(prices) >= 2:
                change = (prices[0].close - prices[-1].close) / prices[-1].close if prices[-1].close else 0
                affected.append({
                    "ticker": r["ticker"],
                    "change_pct": cast(float, change),
                })
        affected.sort(key=lambda x: x["change_pct"])
        long_bonds_hit = any(
            a["change_pct"] < -0.02 for a in affected
        )
        is_market = long_bonds_hit
        if is_market:
            reason = "Рост ключевой ставки ЦБ (+0.5%)"
            recommendation = "YTM вырос — держать до погашения ВЫГОДНЕЕ. Стоп-лосс НЕ срабатывает."
        else:
            reason = "Возможное ухудшение кредитного качества"
            recommendation = "Проверить рейтинги, рассмотреть продажу проблемных позиций."
        return DrawdownAlert(
            current_dd=current_from_peak,
            reason=reason,
            affected_positions=affected[:5],
            is_market_risk=is_market,
            recommendation=recommendation,
        )
    except Exception:
        logger.exception("drawdown_check_error")
        return None
    finally:
        db.close()


def _build_portfolio_history(rows: list[dict[str, Any]]) -> list[float]:
    db = get_session()
    try:
        prices_by_ticker: dict[str, list[float]] = {}
        for r in rows:
            prices = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == r["ticker"])
                .order_by(Price.date.desc())
                .limit(60)
                .all()
            )
            vals = [cast(float, p.close) for p in reversed(prices) if p.close]
            if vals:
                prices_by_ticker[r["ticker"]] = vals
        if not prices_by_ticker:
            return []
        min_len = min(len(v) for v in prices_by_ticker.values())
        hist = []
        for i in range(min_len):
            day_total = sum(
                prices_by_ticker[t][i] * next(
                    (r2["quantity"] for r2 in rows if r2["ticker"] == t), 0
                )
                for t in prices_by_ticker
            )
            hist.append(day_total)
        return hist
    finally:
        db.close()


def format_drawdown_alert(alert: DrawdownAlert) -> str:
    lines = [
        "📉 <b>Просадка портфеля: {:.1%}</b>\n".format(alert.current_dd),
        "Причина: {}".format(alert.reason),
    ]
    if alert.affected_positions:
        lines.append("Пострадали:")
        for a in alert.affected_positions:
            emoji = "🔴" if a["change_pct"] < 0 else "🟢"
            lines.append("  {} {}: {:+.1%}".format(emoji, html_escape(a["ticker"]), a["change_pct"]))
    lines.append("")
    risk_label = "РЫНОЧНЫЙ риск (ставки растут)" if alert.is_market_risk else "КРЕДИТНЫЙ риск (эмитент)"
    lines.append("💡 Анализ:")
    lines.append("  Это {}. {}".format(risk_label, alert.recommendation))
    lines.append("")
    lines.append("📋 Действия:")
    if alert.is_market_risk:
        lines.append("  [ ] Перейти в флоатеры (сценарий B)")
        lines.append("  [ ] Докупить дешевле (усреднение)")
        lines.append("  [ ] Ничего не делать")
    else:
        lines.append("  [ ] Продать проблемные позиции")
        lines.append("  [ ] Проверить рейтинг эмитентов")
        lines.append("  [ ] Ничего не делать")
    return "\n".join(lines)
