from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from src.constants import BROKER_COMMISSION_CONFIG, REBALANCING_TRIGGERS


def get_min_rebalance_threshold(portfolio_value: float, broker_key: str = "tbank") -> float:
    avg_commission = BROKER_COMMISSION_CONFIG.get(broker_key, {}).get("commission_pct", 0.025)
    avg_spread = 0.3
    trade_cost_pct = (avg_commission * 2 + avg_spread) / 100
    min_trade_value = portfolio_value * trade_cost_pct * 3
    if portfolio_value <= 0:
        return 5.0
    threshold_pct = (min_trade_value / portfolio_value) * 100
    return max(threshold_pct, 5.0)


def check_triggers(
    positions: list[dict[str, Any]],
    portfolio_value: float,
    key_rate: Optional[float] = None,
    previous_key_rate: Optional[float] = None,
    rating_changes: Optional[dict[str, str]] = None,
    last_rebalance_date: Optional[datetime] = None,
) -> dict[str, Any]:
    active_triggers: list[dict[str, Any]] = []
    recommendations: list[str] = []

    # 1. Key rate change
    if key_rate is not None and previous_key_rate is not None:
        rate_change_bps = abs(key_rate - previous_key_rate) * 100
        threshold = REBALANCING_TRIGGERS["key_rate_change_bps"]
        if rate_change_bps >= threshold:
            direction = "повышение" if key_rate > previous_key_rate else "снижение"
            active_triggers.append({
                "trigger": "key_rate_change",
                "severity": "high",
                "message": f"Ключевая ставка изменилась на {rate_change_bps:.0f} б.п. ({direction})",
                "value": round(rate_change_bps, 0),
                "threshold": threshold,
            })
            recommendations.append(f"Пересмотреть дюрацию портфеля: {direction} ставки на {rate_change_bps:.0f} б.п.")

    # 2. Price change per position
    for pos in positions:
        ticker = pos.get("ticker", "?")
        price_change_pct = abs(pos.get("profitPercent", 0) or 0)
        threshold = REBALANCING_TRIGGERS["price_change_pct"]
        if price_change_pct >= threshold:
            active_triggers.append({
                "trigger": "price_change",
                "severity": "medium",
                "message": f"{ticker}: изменение цены {price_change_pct:.1f}% (порог {threshold}%)",
                "value": round(price_change_pct, 1),
                "threshold": threshold,
            })
            recommendations.append(f"Проверить фундамент {ticker}: цена изменилась на {price_change_pct:.1f}%")

    # 3. Rating changes
    if rating_changes:
        for ticker, change_type in rating_changes.items():
            if change_type in ("downgrade", "negative_outlook"):
                active_triggers.append({
                    "trigger": "rating_change",
                    "severity": "high",
                    "message": f"{ticker}: рейтинг понижен ({change_type})",
                    "value": change_type,
                    "threshold": "1+ notch",
                })
                recommendations.append(f"Продать {ticker}: рейтинг понижен до неинвестиционного уровня")

    # 4. Allocation deviation (dynamic threshold based on portfolio size)
    min_threshold = get_min_rebalance_threshold(portfolio_value)
    for pos in positions:
        ticker = pos.get("ticker", "?")
        target_pct = pos.get("targetAllocation", 0)
        actual_pct = pos.get("allocation", 0) or 0
        threshold = max(REBALANCING_TRIGGERS["allocation_deviation_pct"], min_threshold)
        if target_pct > 0 and abs(actual_pct - target_pct) >= threshold:
            diff = actual_pct - target_pct
            action = "продать" if diff > 0 else "купить"
            active_triggers.append({
                "trigger": "allocation_deviation",
                "severity": "low",
                "message": f"{ticker}: отклонение {diff:+.1f}% от цели {target_pct}% (порог {threshold:.1f}%)",
                "value": round(abs(diff), 1),
                "threshold": round(threshold, 1),
            })
            recommendations.append(f"{ticker}: {action} {abs(diff):.0f}% для возврата к цели {target_pct}%")

    # 5. Quarterly check
    if last_rebalance_date:
        days_since = (datetime.now() - last_rebalance_date).days
        threshold_days = REBALANCING_TRIGGERS["quarterly_days"]
        if days_since >= threshold_days:
            last_rebalance_date + timedelta(days=threshold_days)
            active_triggers.append({
                "trigger": "quarterly_rebalance",
                "severity": "info",
                "message": f"Плановый пересмотр портфеля: прошло {days_since} дней",
                "value": days_since,
                "threshold": threshold_days,
            })
            recommendations.append("Плановый пересмотр портфеля: проверить соответствие целевым долям")

    return {
        "activeTriggers": active_triggers,
        "triggerCount": len(active_triggers),
        "recommendations": recommendations[:6],
        "severityCount": {
            "high": sum(1 for t in active_triggers if t["severity"] == "high"),
            "medium": sum(1 for t in active_triggers if t["severity"] == "medium"),
            "low": sum(1 for t in active_triggers if t["severity"] == "low"),
            "info": sum(1 for t in active_triggers if t["severity"] == "info"),
        },
    }
