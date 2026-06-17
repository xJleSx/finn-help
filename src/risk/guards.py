import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.config import personal

logger = logging.getLogger(__name__)

# kill switch
_kill_switch_active = False
_daily_loss_limit: Optional[float] = None
_position_limit_pct: Optional[float] = None


def activate_kill_switch(reason: str = ""):
    global _kill_switch_active
    _kill_switch_active = True
    logger.warning("KILL SWITCH ACTIVATED%s", f": {reason}" if reason else "")


def deactivate_kill_switch():
    global _kill_switch_active
    _kill_switch_active = False
    logger.info("Kill switch deactivated")


def is_kill_switch_active() -> bool:
    return _kill_switch_active


def set_daily_loss_limit(pct: float):
    global _daily_loss_limit
    _daily_loss_limit = pct
    logger.info("Daily loss limit set to %.1f%%", pct * 100)


def check_daily_loss(day_return_pct: float) -> bool:
    if _daily_loss_limit is not None and day_return_pct < -_daily_loss_limit:
        logger.warning("Daily loss limit hit: %.2f%% < -%.2f%%", day_return_pct * 100, _daily_loss_limit * 100)
        activate_kill_switch(f"daily loss {day_return_pct:.2%}")
        return True
    return False


def set_max_position_pct(pct: float):
    global _position_limit_pct
    _position_limit_pct = pct
    logger.info("Max position size set to %.1f%%", pct * 100)


def check_position_size(position_value: float, portfolio_value: float) -> tuple[bool, str]:
    pct = position_value / portfolio_value if portfolio_value > 0 else 0
    limit = _position_limit_pct or (personal.get("backtest", {}).get("initial_capital", 1_000_000) * 0.25)

    if pct > limit:
        return False, f"Позиция {pct:.1%} > лимит {limit:.1%}"
    if pct > limit * 0.8:
        return True, f"⚠️ Приближение к лимиту: {pct:.1%} / {limit:.1%}"
    return True, f"✅ {pct:.1%} / {limit:.1%}"


def check_concentration(ticker_weights: dict[str, float]) -> list[str]:
    warnings = []
    for ticker, weight in ticker_weights.items():
        if weight > 0.3:
            warnings.append(f"🔴 {ticker}: {weight:.0%} > 30% — высокая концентрация")
        elif weight > 0.2:
            warnings.append(f"🟡 {ticker}: {weight:.0%} > 20% — повышенная концентрация")
    return warnings


def compute_volatility_target(
    target_vol: float = 0.25,
    current_vol: float = 0.0,
    max_leverage: float = 1.0,
) -> float:
    if current_vol <= 0:
        return max_leverage
    raw = target_vol / current_vol
    return min(raw, max_leverage)


def compute_position_shares(
    portfolio_value: float,
    risk_per_trade: float = 0.02,
    stop_loss_pct: float = 0.05,
    max_shares: int = 1000,
) -> int:
    amount_at_risk = portfolio_value * risk_per_trade
    shares = int(amount_at_risk / (stop_loss_pct * portfolio_value / 100))
    return min(max(shares, 1), max_shares)


# track P&L for the day
_day_start_value: Optional[float] = None
_current_day_value: Optional[float] = None


def start_day(portfolio_value: float):
    global _day_start_value, _current_day_value
    _day_start_value = portfolio_value
    _current_day_value = portfolio_value
    logger.info("Day start value: %.2f", portfolio_value)


def update_day_value(current_value: float):
    global _current_day_value
    _current_day_value = current_value


def get_day_pnl() -> tuple[float, float]:
    if _day_start_value is None or _current_day_value is None:
        return 0.0, 0.0
    pnl = _current_day_value - _day_start_value
    pnl_pct = pnl / _day_start_value if _day_start_value else 0
    return pnl, pnl_pct
