import asyncio
import datetime
import logging
from typing import Optional

import pandas as pd

from src.config import personal

logger = logging.getLogger(__name__)

_risk_lock: asyncio.Lock | None = None


def _get_risk_lock() -> asyncio.Lock:
    global _risk_lock
    if _risk_lock is None:
        _risk_lock = asyncio.Lock()
    return _risk_lock


_CB_KILL_SWITCH_REASONS: set[str] = set()


def _cb_state_change_handler(name: str, old_state: object, new_state: object) -> None:
    from src.core.resilience import CircuitState

    if new_state is CircuitState.OPEN:
        reason = f"circuit_breaker.{name}.opened"
        _CB_KILL_SWITCH_REASONS.add(name)
        logger.warning("KILL SWITCH via circuit breaker: %s", reason)
        activate_kill_switch(reason)
    elif new_state is CircuitState.CLOSED and name in _CB_KILL_SWITCH_REASONS:
        _CB_KILL_SWITCH_REASONS.discard(name)
        if not _CB_KILL_SWITCH_REASONS:
            logger.info("Circuit breaker %s recovered — kill switch may be manually deactivated", name)


def wire_circuit_breakers_to_kill_switch() -> None:
    from src.core.resilience import get_circuit_breaker

    for cb_name in ("tbank", "tbank_orders", "tbank_market"):
        try:
            cb = get_circuit_breaker(cb_name)
            cb.on_state_change(_cb_state_change_handler)
        except Exception:
            logger.exception("Unhandled exception")
            logger.warning("Could not wire circuit breaker %s to kill switch", cb_name)


def circuit_breaker_kill_switch_active() -> bool:
    return len(_CB_KILL_SWITCH_REASONS) > 0


# kill switch
_kill_switch_active = False
_daily_loss_limit: Optional[float] = None
_position_limit_pct: Optional[float] = None

# max drawdown
_peak_value: Optional[float] = None
_current_portfolio_value: Optional[float] = None
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


_INSANE_OPT_IN_KEY = "allow_insane_profile"


def _resolve_risk_profile() -> dict[str, float]:
    profile = str(personal.get("risk_profile") or "balanced").lower()
    mapping = RISK_PROFILE_MAP.get(profile)
    if mapping is None:
        return RISK_PROFILE_MAP["balanced"]
    if profile == "insane":
        allow = personal.get(_INSANE_OPT_IN_KEY, False)
        if not allow:
            logger.warning(
                "Risk profile 'insane' requires '%s=true' in personal_settings.yaml. Falling back to 'aggressive'.",
                _INSANE_OPT_IN_KEY,
            )
            return RISK_PROFILE_MAP["aggressive"]
    return mapping


def _load_risk_params() -> None:
    mapping = _resolve_risk_profile()
    global _position_limit_pct, _daily_loss_limit, _max_drawdown_pct
    _position_limit_pct = mapping["max_position_pct"]
    _daily_loss_limit = mapping["daily_loss_limit"]
    _max_drawdown_pct = mapping["max_drawdown_pct"]


def risk_per_trade() -> float:
    return _resolve_risk_profile()["risk_per_trade"]


def max_position_pct() -> float:
    return _resolve_risk_profile()["max_position_pct"]


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
    return _kill_switch_active or circuit_breaker_kill_switch_active()


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
    global _peak_value, _current_portfolio_value
    _current_portfolio_value = current_value
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
    if _peak_value is None or _current_portfolio_value is None or _peak_value <= 0:
        return 0.0
    return (_current_portfolio_value - _peak_value) / _peak_value


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
    async with _get_risk_lock():
        return check_daily_loss(day_return_pct)


async def async_update_drawdown(current_value: float) -> float:
    async with _get_risk_lock():
        return update_drawdown(current_value)


async def async_activate_kill_switch(reason: str = "") -> None:
    async with _get_risk_lock():
        activate_kill_switch(reason)


async def async_deactivate_kill_switch() -> None:
    async with _get_risk_lock():
        deactivate_kill_switch()


async def async_is_kill_switch_active() -> bool:
    async with _get_risk_lock():
        return is_kill_switch_active()


async def async_update_day_value(current_value: float) -> None:
    async with _get_risk_lock():
        update_day_value(current_value)


async def async_start_day(value: float) -> None:
    async with _get_risk_lock():
        start_day(value)


try:
    _load_risk_params()
    logger.info(
        "Risk params loaded: position_limit=%.0f%%, daily_loss=%.0f%%, max_drawdown=%.0f%%",
        _position_limit_pct * 100 if _position_limit_pct else 0,
        _daily_loss_limit * 100 if _daily_loss_limit else 0,
        _max_drawdown_pct * 100 if _max_drawdown_pct else 0,
    )
except Exception:
    logger.exception("Unhandled exception")
    logger.warning("Could not load risk params from config, using defaults")


# ═══════════════════════════════════════════════════════════════
# Weekly Loss Tracker
# ═══════════════════════════════════════════════════════════════


class WeeklyLossTracker:
    def __init__(self, initial_capital: float = 100000.0):
        self._initial_capital = initial_capital
        self._trades: list[tuple[float, datetime.date]] = []

    def record_trade(self, pnl: float, timestamp: datetime.date) -> None:
        self._trades.append((pnl, timestamp))

    def current_week_pnl(self) -> float:
        today = datetime.date.today()
        total = 0.0
        for pnl, ts in self._trades:
            if self._same_week(ts, today):
                total += pnl
        return total

    def weekly_loss_level(self) -> str:
        pnl = self.current_week_pnl()
        pnl_pct = pnl / self._initial_capital if self._initial_capital else 0.0
        if pnl_pct >= -0.05:
            return "normal"
        if pnl_pct >= -0.07:
            return "reduce_50"
        if pnl_pct >= -0.10:
            return "minimum_only"
        return "full_halt"

    def consecutive_loss_days(self) -> int:
        from collections import defaultdict

        daily_pnl: dict[datetime.date, float] = defaultdict(float)
        for pnl, ts in self._trades:
            daily_pnl[ts] += pnl
        sorted_days = sorted(daily_pnl, reverse=True)
        count = 0
        for day in sorted_days:
            if daily_pnl[day] < 0:
                count += 1
            else:
                break
        return count

    def reset_week(self) -> None:
        self._trades.clear()

    @staticmethod
    def _same_week(d1: datetime.date, d2: datetime.date) -> bool:
        iso1 = d1.isocalendar()
        iso2 = d2.isocalendar()
        return iso1[0] == iso2[0] and iso1[1] == iso2[1]


# ═══════════════════════════════════════════════════════════════
# Drawdown Stage Manager
# ═══════════════════════════════════════════════════════════════

_DRAWDOWN_STAGE_RESPONSES: dict[str, str] = {
    "normal": "No action required",
    "caution": "Reduce position sizes, tighten stops",
    "warning": "Reduce exposure by 50%, halt new positions",
    "critical": "Close high-risk positions, reduce to minimum exposure",
    "emergency": "Liquidate all positions, halt trading",
}


class DrawdownStageManager:
    def __init__(self) -> None:
        self._peak: float | None = None
        self._current: float | None = None

    def update(self, equity_curve: list[float] | pd.Series) -> None:
        if isinstance(equity_curve, pd.Series):
            values = equity_curve.tolist()
        else:
            values = list(equity_curve)
        if not values:
            return
        self._current = values[-1]
        running_peak = max(values)
        if self._peak is None or running_peak > self._peak:
            self._peak = running_peak

    def current_drawdown(self) -> float:
        if self._peak is None or self._current is None or self._peak <= 0:
            return 0.0
        return (self._current - self._peak) / self._peak

    def stage(self) -> str:
        dd = abs(self.current_drawdown())
        if dd < 0.05:
            return "normal"
        if dd < 0.10:
            return "caution"
        if dd < 0.15:
            return "warning"
        if dd < 0.20:
            return "critical"
        return "emergency"

    def response(self) -> str:
        return _DRAWDOWN_STAGE_RESPONSES.get(self.stage(), "Unknown stage")


# ═══════════════════════════════════════════════════════════════
# Exposure limit function
# ═══════════════════════════════════════════════════════════════


def compute_exposure_limit(drawdown_pct: float, base_exposure: float = 0.8) -> float:
    dd = abs(drawdown_pct)
    if dd > 0.15:
        return 0.20
    if dd > 0.10:
        return 0.30
    if dd > 0.05:
        return 0.50
    return base_exposure


# ═══════════════════════════════════════════════════════════════
# Consecutive loss / win tracking
# ═══════════════════════════════════════════════════════════════


def track_consecutive_losses(trade_results: list[float]) -> tuple[int, int]:
    consecutive_losses = 0
    consecutive_wins = 0
    for pnl in trade_results:
        if pnl < 0:
            consecutive_losses += 1
            consecutive_wins = 0
        elif pnl > 0:
            consecutive_wins += 1
            consecutive_losses = 0
    return consecutive_losses, consecutive_wins


# ═══════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════

VALID_BREAKER_TYPES = frozenset({"time", "loss", "volatility"})


class CircuitBreaker:
    def __init__(self, breaker_type: str) -> None:
        if breaker_type not in VALID_BREAKER_TYPES:
            raise ValueError(f"Invalid breaker_type '{breaker_type}'. Choose from {sorted(VALID_BREAKER_TYPES)}")
        self._breaker_type = breaker_type
        self._triggered: bool = False
        self._triggered_at: datetime.datetime | None = None
        self._cooldown_seconds: float = 3600.0
        self._daily_loss_limit: float = float("inf")
        self._weekly_loss_limit: float = float("inf")
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0
        self._volatility_samples: list[float] = []
        self._vol_percentile_threshold: float = 0.95

    def record_trade(self, pnl: float, ts: datetime.date | None = None) -> None:
        self._daily_pnl += pnl
        self._weekly_pnl += pnl

    def reset_pnl(self) -> None:
        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0

    def record_volatility(self, value: float) -> None:
        self._volatility_samples.append(value)

    def time_breaker(self, cooldown_minutes: float = 60.0) -> None:
        self._cooldown_seconds = cooldown_minutes * 60.0
        self._triggered = True
        self._triggered_at = datetime.datetime.now()

    def loss_breaker(self, daily_loss_limit: float, weekly_loss_limit: float) -> None:
        self._daily_loss_limit = daily_loss_limit
        self._weekly_loss_limit = weekly_loss_limit
        if self._daily_pnl <= -daily_loss_limit or self._weekly_pnl <= -weekly_loss_limit:
            self._triggered = True
            self._triggered_at = datetime.datetime.now()

    def volatility_breaker(self, vol_percentile_threshold: float = 0.95) -> None:
        self._vol_percentile_threshold = vol_percentile_threshold
        if len(self._volatility_samples) < 2:
            return
        sorted_vols = sorted(self._volatility_samples)
        idx = min(int(len(sorted_vols) * vol_percentile_threshold), len(sorted_vols) - 1)
        threshold_val = sorted_vols[idx]
        if self._volatility_samples[-1] >= threshold_val:
            self._triggered = True
            self._triggered_at = datetime.datetime.now()

    def is_triggered(self) -> bool:
        if not self._triggered or self._triggered_at is None:
            return False
        elapsed = (datetime.datetime.now() - self._triggered_at).total_seconds()
        if elapsed >= self._cooldown_seconds:
            self._triggered = False
            self._triggered_at = None
            return False
        return True

    def remaining_cooldown(self) -> float:
        if not self._triggered or self._triggered_at is None:
            return 0.0
        elapsed = (datetime.datetime.now() - self._triggered_at).total_seconds()
        return max(self._cooldown_seconds - elapsed, 0.0)

    def reset(self) -> None:
        self._triggered = False
        self._triggered_at = None


# ═══════════════════════════════════════════════════════════════
# Correlation risk adjustment
# ═══════════════════════════════════════════════════════════════


def compute_correlation_risk_adjustment(
    position_sizes: dict[str, float],
    correlations: dict[str, float],
    max_correlation: float = 0.7,
) -> float:
    tickers = list(position_sizes.keys())
    if len(tickers) < 2:
        return 1.0
    total_size = sum(position_sizes.values())
    if total_size <= 0:
        return 1.0
    weighted_corr_sum = 0.0
    weight_sum = 0.0
    pairs_considered = 0
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            a, b = tickers[i], tickers[j]
            pair_key = f"{a}_{b}" if a < b else f"{b}_{a}"
            corr = correlations.get(pair_key)
            if corr is None:
                corr = correlations.get(f"{b}_{a}")
            if corr is not None:
                w = (position_sizes[a] + position_sizes[b]) / 2.0
                weighted_corr_sum += corr * w
                weight_sum += w
                pairs_considered += 1
    if pairs_considered == 0 or weight_sum <= 0:
        return 1.0
    avg_corr = weighted_corr_sum / weight_sum
    if avg_corr <= max_correlation:
        return 1.0
    excess = (avg_corr - max_correlation) / (1.0 - max_correlation)
    return max(0.0, 1.0 - excess)
