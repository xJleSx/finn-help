import asyncio
import logging
from typing import Optional

from src.config import personal

logger = logging.getLogger(__name__)

_risk_lock = asyncio.Lock()

# kill switch
_kill_switch_active = False
_daily_loss_limit: Optional[float] = None
_position_limit_pct: Optional[float] = None

# max drawdown
_peak_value: Optional[float] = None
_max_drawdown_pct: float = 0.20


RISK_PROFILE_MAP = {
    "ultra_conservative": {
        "risk_per_trade": 0.005,
        "max_position_pct": 0.05,
        "max_drawdown_pct": 0.05,
        "daily_loss_limit": 0.02,
    },
    "conservative": {
        "risk_per_trade": 0.01,
        "max_position_pct": 0.15,
        "max_drawdown_pct": 0.10,
        "daily_loss_limit": 0.03,
    },
    "balanced": {
        "risk_per_trade": 0.02,
        "max_position_pct": 0.25,
        "max_drawdown_pct": 0.15,
        "daily_loss_limit": 0.04,
    },
    "aggressive": {
        "risk_per_trade": 0.03,
        "max_position_pct": 0.35,
        "max_drawdown_pct": 0.20,
        "daily_loss_limit": 0.05,
    },
    "insane": {
        "risk_per_trade": 0.10,
        "max_position_pct": 0.75,
        "max_drawdown_pct": 0.35,
        "daily_loss_limit": 0.15,
    },
}


def _load_risk_params() -> None:
    profile = (personal.get("risk_profile") or "balanced").lower()
    mapping = RISK_PROFILE_MAP.get(profile, RISK_PROFILE_MAP["balanced"])
    global _position_limit_pct, _daily_loss_limit, _max_drawdown_pct
    _position_limit_pct = mapping["max_position_pct"]
    _daily_loss_limit = mapping["daily_loss_limit"]
    _max_drawdown_pct = mapping["max_drawdown_pct"]


def risk_per_trade() -> float:
    profile = (personal.get("risk_profile") or "balanced").lower()
    return RISK_PROFILE_MAP.get(profile, RISK_PROFILE_MAP["balanced"])["risk_per_trade"]


def max_position_pct() -> float:
    profile = (personal.get("risk_profile") or "balanced").lower()
    return RISK_PROFILE_MAP.get(profile, RISK_PROFILE_MAP["balanced"])["max_position_pct"]


def max_drawdown_pct() -> float:
    return _max_drawdown_pct


def activate_kill_switch(reason: str = "") -> None:
    global _kill_switch_active
    _kill_switch_active = True
    logger.warning("KILL SWITCH ACTIVATED%s", f": {reason}" if reason else "")


def deactivate_kill_switch() -> None:
    global _kill_switch_active
    _kill_switch_active = False
    logger.info("Kill switch deactivated")


def is_kill_switch_active() -> bool:
    return _kill_switch_active


def set_daily_loss_limit(pct: float) -> None:
    global _daily_loss_limit
    _daily_loss_limit = pct
    logger.info("Daily loss limit set to %.1f%%", pct * 100)


def set_max_drawdown_pct(pct: float) -> None:
    global _max_drawdown_pct
    _max_drawdown_pct = pct
    logger.info("Max drawdown set to %.1f%%", pct * 100)


def check_daily_loss(day_return_pct: float) -> bool:
    if _daily_loss_limit is not None and day_return_pct < -_daily_loss_limit:
        logger.warning("Daily loss limit hit: %.2f%% < -%.2f%%", day_return_pct * 100, _daily_loss_limit * 100)
        activate_kill_switch(f"daily loss {day_return_pct:.2%}")
        return True
    return False


def set_max_position_pct(pct: float) -> None:
    global _position_limit_pct
    _position_limit_pct = pct
    logger.info("Max position size set to %.1f%%", pct * 100)


def check_position_size(position_value: float, portfolio_value: float) -> tuple[bool, str]:
    pct = position_value / portfolio_value if portfolio_value > 0 else 0
    limit = _position_limit_pct if _position_limit_pct is not None else 0.25

    if pct > limit:
        return False, f"Позиция {pct:.1%} > лимит {limit:.1%}"
    if pct >= limit * 0.8:
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
    current_price: float = 1.0,
    max_shares: int = 1000,
    current_vol: float = 0.0,
    target_vol: float = 0.25,
) -> int:
    vol_adj = compute_volatility_target(target_vol, current_vol, max_leverage=1.0)
    amount_at_risk = portfolio_value * risk_per_trade * vol_adj
    risk_per_share = current_price * stop_loss_pct
    if risk_per_share <= 0:
        return min(max_shares, 1)
    shares = int(amount_at_risk / risk_per_share)
    return min(max(shares, 1), max_shares)


VAR_LIMIT: float = 0.05
_MAX_LEVERAGE: float = 1.0


def set_max_leverage(n: float) -> None:
    global _MAX_LEVERAGE
    _MAX_LEVERAGE = n


def check_leverage(current_leverage: float) -> tuple[bool, str]:
    if current_leverage > _MAX_LEVERAGE:
        return False, f"Плечо {current_leverage:.1f}x > лимит {_MAX_LEVERAGE:.1f}x"
    return True, f"Плечо {current_leverage:.1f}x в пределах {_MAX_LEVERAGE:.1f}x"


def set_var_limit(pct: float) -> None:
    global VAR_LIMIT
    VAR_LIMIT = pct


def check_var_limit(var_95: float) -> tuple[bool, str]:
    if var_95 > VAR_LIMIT:
        return False, f"VaR(95%) {var_95:.1%} > лимит {VAR_LIMIT:.1%}"
    return True, f"VaR(95%) {var_95:.1%} в пределах {VAR_LIMIT:.1%}"


MIN_DAILY_VOLUME: float = 1_000_000.0
MIN_LIQUIDITY_RATIO = 2


def set_min_volume(vol: float) -> None:
    global MIN_DAILY_VOLUME
    MIN_DAILY_VOLUME = vol


def check_liquidity(avg_volume: float, order_value: float) -> tuple[bool, str]:
    if avg_volume <= 0:
        return False, "Нет данных об объёмах"
    if order_value > avg_volume:
        return False, f"Сумма заявки {order_value:,.0f} ₽ превышает среднедневной объём {avg_volume:,.0f} ₽"
    ratio = avg_volume / order_value if order_value > 0 else float("inf")
    if ratio < MIN_LIQUIDITY_RATIO:
        return True, f"⚠️ Низкая ликвидность: объём превышает заявку в {ratio:.0f}x"
    return True, f"✅ Ликвидность: {ratio:.0f}x запас"


NEGATIVE_SENTIMENT_THRESHOLD = -0.3


def check_news_sentiment(news_scores: list[float]) -> tuple[bool, str]:
    if not news_scores:
        return True, "Нет новостей для проверки"
    avg = sum(news_scores) / len(news_scores)
    min_news = min(news_scores)
    if avg < NEGATIVE_SENTIMENT_THRESHOLD or min_news < -0.5:
        return False, f"Негативный новостной фон: средний сентимент {avg:.2f}, мин {min_news:.2f}"
    if avg < -0.1:
        return True, f"⚠️ Осторожно: сентимент {avg:.2f}"
    return True, f"✅ Новостной фон: {avg:.2f}"


def update_drawdown(current_value: float) -> float:
    global _peak_value
    if _peak_value is None or current_value > _peak_value:
        _peak_value = current_value
    if _peak_value <= 0:
        return 0.0
    dd = (current_value - _peak_value) / _peak_value
    if dd < -_max_drawdown_pct:
        activate_kill_switch(f"max drawdown {dd:.2%} exceeded threshold {_max_drawdown_pct:.2%}")
    return dd


def reset_peak(value: float) -> None:
    global _peak_value
    _peak_value = value


def current_drawdown() -> float:
    return 0.0


# track P&L for the day
_day_start_value: Optional[float] = None
_current_day_value: Optional[float] = None


def start_day(portfolio_value: float) -> None:
    global _day_start_value, _current_day_value
    _day_start_value = portfolio_value
    _current_day_value = portfolio_value
    logger.info("Day start value: %.2f", portfolio_value)


def update_day_value(current_value: float) -> None:
    global _current_day_value
    _current_day_value = current_value


def get_day_pnl() -> tuple[float, float]:
    if _day_start_value is None or _current_day_value is None:
        return 0.0, 0.0
    pnl = _current_day_value - _day_start_value
    pnl_pct = pnl / _day_start_value if _day_start_value else 0
    return pnl, pnl_pct


async def async_check_daily_loss(day_return_pct: float) -> bool:
    async with _risk_lock:
        return check_daily_loss(day_return_pct)


async def async_update_drawdown(current_value: float) -> float:
    async with _risk_lock:
        return update_drawdown(current_value)


async def async_activate_kill_switch(reason: str = "") -> None:
    async with _risk_lock:
        activate_kill_switch(reason)


async def async_deactivate_kill_switch() -> None:
    async with _risk_lock:
        deactivate_kill_switch()


async def async_is_kill_switch_active() -> bool:
    async with _risk_lock:
        return is_kill_switch_active()


async def async_update_day_value(current_value: float) -> None:
    async with _risk_lock:
        update_day_value(current_value)


async def async_start_day(value: float) -> None:
    async with _risk_lock:
        start_day(value)


try:
    _load_risk_params()
    logger.info("Risk params loaded: position_limit=%.0f%%, daily_loss=%.0f%%, max_drawdown=%.0f%%",
                 _position_limit_pct * 100 if _position_limit_pct else 0,
                 _daily_loss_limit * 100 if _daily_loss_limit else 0,
                 _max_drawdown_pct * 100 if _max_drawdown_pct else 0)
except Exception:
    logger.warning("Could not load risk params from config, using defaults")
