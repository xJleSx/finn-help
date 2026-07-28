from __future__ import annotations

from typing import Any


def scenario_b_plan(
    positions: list[dict[str, Any]],
    portfolio_value: float,
    current_duration: float,
    rate_unchanged_months: int,
    inflation_pct: float,
    deposit_rate: float,
) -> dict[str, Any]:
    is_active = rate_unchanged_months >= 4 or (rate_unchanged_months >= 2 and inflation_pct > 8.0)

    sell_recs = []
    buy_recs = []
    actions = []

    for pos in positions:
        ticker = pos.get("ticker", "")
        dur = pos.get("duration", 0) or 0
        pct = (pos.get("totalValue", 0) or 0) / portfolio_value * 100 if portfolio_value > 0 else 0

        if dur > 5 and is_active:
            sell_recs.append({
                "ticker": ticker,
                "duration": dur,
                "positionPct": round(pct, 1),
                "reason": f"Дюрация {dur:.1f}л — высокий риск при сохранении высоких ставок",
            })
            actions.append(f"Продать {ticker} (дюрация {dur:.1f}л, {pct:.0f}% портфеля)")

    if is_active:
        buy_recs.extend([
            {
                "ticker": "ОФЗ 26234 / 26235",
                "type": "short_ofz",
                "reason": "Погашение 2027-2028 — низкая дюрация, защита от роста ставок",
                "suggestedPct": 30,
            },
            {
                "ticker": "ОФЗ-ПК (флоатеры)",
                "type": "floater",
                "reason": "Купон привязан к RUONIA — растёт вместе со ставкой",
                "suggestedPct": 25,
            },
        ])

        if deposit_rate > 15:
            buy_recs.append({
                "ticker": "Депозит/вклад",
                "type": "deposit",
                "reason": f"Депозит {deposit_rate:.1f}% > YTM облигаций — без рыночного риска",
                "suggestedPct": 15,
            })

        buy_recs.append({
            "ticker": "LQDT / TMON (денежный рынок)",
            "type": "money_market",
            "reason": "Ликвидный резерв для входа после снижения ставок",
            "suggestedPct": 10,
        })

    total_sell_pct = sum(s.get("positionPct", 0) for s in sell_recs)
    total_buy_pct = sum(b.get("suggestedPct", 0) for b in buy_recs)

    return {
        "scenarioBActive": is_active,
        "triggerReason": _trigger_reason(rate_unchanged_months, inflation_pct, is_active),
        "currentDuration": round(current_duration, 1),
        "targetDuration": 2.0,
        "sellRecommendations": sell_recs,
        "buyRecommendations": buy_recs,
        "actions": actions[:6],
        "totalSellPct": round(total_sell_pct, 1),
        "totalBuyPct": round(total_buy_pct, 1),
        "expectedYieldImpact": "-2% to -3% vs baseline scenario",
        "reinvestmentHint": "После снижения ставок переключиться обратно в длинные ОФЗ",
    }


def _trigger_reason(months: int, inflation: float, active: bool) -> str:
    if not active:
        return f"Пока не активирован: ставка без изменений {months} мес."
    if months >= 4:
        return f"ЦБ не меняет ставку {months}+ месяцев"
    if inflation > 8:
        return f"Инфляция {inflation:.1f}% — превышает порог 8%, ставка не снижается"
    return "Сработали триггеры сценария B"
