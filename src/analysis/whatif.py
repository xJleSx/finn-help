import logging

import numpy as np

from src.db.connection import get_session
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)


def whatif_scenario(
    ticker: str,
    shock_pct: float,
    portfolio_value: float = 1_000_000,
) -> str:
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
        if not inst:
            return f"Инструмент {ticker} не найден"

        price = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.desc()).first()
        if not price or not price.close:
            return f"Нет цены для {ticker}"

        current_price = price.close
        shocked_price = current_price * (1 + shock_pct)

        # find correlating tickers
        correlated = _find_correlated(db, ticker, limit=3)

        impact_on_portfolio = portfolio_value * abs(shock_pct) * 0.05  # assume 5% allocation

        lines = [
            f"📉 *What-If: {ticker}*",
            f"   Сценарий: {shock_pct:+.0%}",
            "",
            f"   Цена сейчас: {current_price:.2f} ₽",
            f"   Цена после: {shocked_price:.2f} ₽",
            f"   Изменение: {shock_pct:+.0%}",
            "",
            f"   💰 Влияние на портфель {portfolio_value:,.0f} ₽:",
            f"   {impact_on_portfolio:+,.0f} ₽ (при доле ~5%)",
        ]

        if correlated:
            lines.append("")
            lines.append("*Коррелированные тикеры:*")
            for t, corr_val in correlated:
                emoji = "🔴" if abs(corr_val) > 0.7 else "🟡"
                implied = shock_pct * corr_val
                lines.append(f"   {emoji} {t}: r={corr_val:.2f} → {implied:+.1%}")

        return "\n".join(lines)
    finally:
        db.close()


def whatif_macro(shock_name: str, portfolio_value: float = 1_000_000) -> str:
    scenarios = {
        "oil40": ("Нефть по $40", {"Нефть и газ": -0.30, "overall": -0.10}),
        "rate25": ("Ключевая ставка 25%", {"Банки": -0.20, "overall": -0.08}),
        "rubdown20": ("Рубль -20%", {"Потреб": -0.15, "IT": -0.12, "overall": -0.08}),
        "sanctions2022": ("Санкции 2022", {"overall": -0.40}),
        "covid2020": ("COVID-19", {"overall": -0.30}),
    }

    if shock_name not in scenarios:
        available = ", ".join(scenarios.keys())
        return f"Неизвестный сценарий. Доступны: {available}"

    name, shocks = scenarios[shock_name]
    overall = shocks.get("overall", 0)
    loss = portfolio_value * overall

    lines = [
        f"🌍 *Макро-сценарий: {name}*",
        f"   Портфель: {portfolio_value:,.0f} ₽",
        f"   Ожидаемое изменение: {overall:+.0%}",
        f"   {loss:+,.0f} ₽",
    ]

    sector_lines = [(s, v) for s, v in shocks.items() if s != "overall"]
    if sector_lines:
        lines.append("")
        lines.append("*По секторам:*")
        for sector, val in sector_lines:
            sector_impact = portfolio_value * val * 0.3
            lines.append(f"   {sector}: {val:+.0%} ({sector_impact:+,.0f} ₽)")

    return "\n".join(lines)


def _find_correlated(db, ticker: str, limit: int = 3) -> list[tuple[str, float]]:

    inst = db.query(Instrument).filter_by(ticker=ticker).first()
    if not inst:
        return []

    ticker_prices = db.query(Price).filter_by(instrument_id=inst.id).order_by(Price.date.asc()).all()
    if len(ticker_prices) < 30:
        return []

    other_insts = db.query(Instrument).filter(Instrument.ticker != ticker).limit(20).all()
    results = []
    for other in other_insts:
        other_prices = (
            db.query(Price).filter_by(instrument_id=other.id).order_by(Price.date.asc()).all()
        )
        if len(other_prices) < 30:
            continue

        min_len = min(len(ticker_prices), len(other_prices))
        a = np.array([p.close for p in ticker_prices[-min_len:]])
        b = np.array([p.close for p in other_prices[-min_len:]])
        ret_a = np.diff(a) / a[:-1]
        ret_b = np.diff(b) / b[:-1]
        if len(ret_a) < 10 or np.std(ret_a) == 0 or np.std(ret_b) == 0:
            continue
        corr = float(np.corrcoef(ret_a, ret_b)[0, 1])
        if abs(corr) > 0.3:
            results.append((other.ticker, corr))

    results.sort(key=lambda x: abs(x[1]), reverse=True)
    return results[:limit]
