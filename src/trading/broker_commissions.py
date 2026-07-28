from __future__ import annotations

from typing import Any

from src.config import BROKER_COMMISSION_CONFIG


def get_commission_config(broker_key: str = "tbank") -> dict[str, Any]:
    return dict(BROKER_COMMISSION_CONFIG.get(broker_key, BROKER_COMMISSION_CONFIG["tbank"]))


def calc_broker_commission(amount: float, broker_key: str = "tbank") -> float:
    config = get_commission_config(broker_key)
    commission_pct = config["commission_pct"]
    min_commission = config.get("min_rub", 0)
    raw = amount * commission_pct / 100
    if raw < min_commission:
        raw = min_commission
    return round(raw, 2)


def calc_total_trade_cost(buy_amount: float, sell_amount: float, broker_key: str = "tbank") -> dict[str, Any]:
    buy_comm = calc_broker_commission(buy_amount, broker_key)
    sell_comm = calc_broker_commission(sell_amount, broker_key)
    return {
        "buyCommission": buy_comm,
        "sellCommission": sell_comm,
        "totalCommission": round(buy_comm + sell_comm, 2),
        "broker": broker_key,
    }
