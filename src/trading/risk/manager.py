from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    if len(returns) < 10:
        return 0.0
    return float(abs(np.percentile(returns, (1 - confidence) * 100)))


def compute_var(price_series: list[float], confidence: float = 0.95) -> dict[str, float]:
    arr = np.array(price_series, dtype=float)
    if len(arr) < 10:
        return {"var_95": 0.0, "var_99": 0.0, "cvar_95": 0.0}

    returns = np.diff(arr) / arr[:-1]

    var_95 = historical_var(returns, 0.95)
    var_99 = historical_var(returns, 0.99)

    cvar_95 = float(abs(np.mean(returns[returns <= -var_95]))) if len(returns[returns <= -var_95]) > 0 else var_95

    return {
        "var_95": round(var_95 * 100, 2),
        "var_99": round(var_99 * 100, 2),
        "cvar_95": round(cvar_95 * 100, 2),
    }


def compute_stop_loss(price: float, atr: float | None, multiplier: float = 2.0) -> dict[str, float] | None:
    if atr is None or atr <= 0 or price <= 0:
        return None
    stop_distance = atr * multiplier
    return {
        "stop_loss": round(price - stop_distance, 2),
        "stop_loss_pct": round(-(stop_distance / price) * 100, 2),
        "atr_multiple": multiplier,
    }


def compute_concentration_limit(capital: float, price: float, max_position_pct: float = 20.0) -> dict[str, float | int]:
    if price <= 0:
        return {"shares": 0, "amount": 0.0, "max_pct": max_position_pct}
    max_amount = capital * max_position_pct / 100
    shares = int(max_amount / price)
    return {
        "shares": shares,
        "amount": round(shares * price, 2),
        "max_pct": max_position_pct,
    }


def compute_risk_score(var_95: float, stop_loss_pct: float, atr_ratio: float | None = None) -> float:
    score = 0.0
    score += min(var_95 / 5.0, 3.0)
    score += min(abs(stop_loss_pct) / 5.0, 2.0)
    if atr_ratio is not None:
        score += min(atr_ratio / 3.0, 2.0)
    return round(min(score / 7.0, 1.0), 3)


def kelly_fraction(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    max_kelly: float = 0.25,
) -> float:
    if avg_loss_pct <= 0:
        return 0.0
    b = abs(avg_win_pct / avg_loss_pct)
    p = win_rate
    q = 1 - p
    if b <= 0:
        return 0.0
    kelly = (b * p - q) / b
    return max(0.0, min(kelly, max_kelly))


def compute_position_size(
    capital: float,
    price: float,
    risk_per_trade_pct: float = 2.0,
    stop_loss_pct: float | None = None,
    method: str = "fixed_fractional",
    win_rate: float = 0.0,
    avg_win_pct: float = 0.0,
    avg_loss_pct: float = 0.0,
) -> dict[str, float | int | str]:
    if price <= 0:
        return {"shares": 0, "amount": 0.0, "risk_amount": 0.0}

    if method == "kelly" and win_rate > 0 and avg_win_pct > 0 and avg_loss_pct > 0:
        fraction = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
        max_risk_amount = capital * fraction
    else:
        max_risk_amount = capital * risk_per_trade_pct / 100

    if stop_loss_pct is not None and stop_loss_pct != 0:
        risk_per_share = price * abs(stop_loss_pct) / 100
        shares = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0
    else:
        shares = int(max_risk_amount / (price * 0.05))

    amount = round(shares * price, 2)
    return {
        "shares": shares,
        "amount": amount,
        "risk_amount": round(max_risk_amount, 2),
        "risk_pct": risk_per_trade_pct,
        "method": method,
    }


def compute_vol_adjusted_size(
    account_value: float,
    risk_per_trade: float,
    atr: float,
    entry_price: float,
    atr_multiplier: float = 2.0,
) -> int:
    if atr <= 0 or entry_price <= 0 or account_value <= 0 or risk_per_trade <= 0:
        return 0
    risk_amount = account_value * risk_per_trade
    position_value = risk_amount / (atr * atr_multiplier)
    shares = int(position_value / entry_price)
    return max(shares, 0)


def compute_liquidity_constrained_size(
    position_size: int,
    daily_volume: float,
    max_volume_pct: float = 0.1,
) -> int:
    if daily_volume <= 0 or position_size <= 0:
        return 0
    max_by_volume = int(daily_volume * max_volume_pct)
    return min(position_size, max_by_volume)


def compute_anti_martingale_size(
    base_size: float,
    consecutive_wins: int,
    multiplier: float = 1.5,
    max_multiplier: float = 3.0,
) -> float:
    if base_size <= 0:
        return 0.0
    if consecutive_wins > 0:
        factor = min(multiplier**consecutive_wins, max_multiplier)
    else:
        factor = max(multiplier**consecutive_wins, 1.0 / max_multiplier)
    return base_size * factor


def compute_sizing_ladder(
    account_value: float,
    prices: float | list[float] | np.ndarray,
    risk_params: dict[str, Any],
) -> dict[str, float | int | str]:
    price = (float(prices[-1]) if len(prices) > 0 else 0.0) if isinstance(prices, (list, np.ndarray)) else float(prices)

    if price <= 0 or account_value <= 0:
        return {"shares": 0, "amount": 0.0, "method": "ladder"}

    candidates_list: list[int] = []

    risk_pt = risk_params.get("risk_per_trade", 0.02)

    # fixed_fractional
    sl_pct = risk_params.get("stop_loss_pct")
    ff = compute_position_size(account_value, price, risk_per_trade_pct=risk_pt * 100, stop_loss_pct=sl_pct)
    candidates_list.append(int(ff["shares"]))

    # volatility_adjusted
    atr = risk_params.get("atr")
    if atr is not None and atr > 0:
        va = compute_vol_adjusted_size(account_value, risk_pt, atr, price)
        candidates_list.append(va)

    # kelly
    win_rate = risk_params.get("win_rate", 0.0)
    payoff_ratio = risk_params.get("payoff_ratio")
    if win_rate > 0 and payoff_ratio is not None and payoff_ratio > 0:
        avg_win_pct = risk_params.get("avg_win_pct", payoff_ratio * 10.0)
        avg_loss_pct = risk_params.get("avg_loss_pct", 10.0)
        kelly_frac = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
        if kelly_frac > 0:
            shares_kelly = int(account_value * kelly_frac / price)
            candidates_list.append(shares_kelly)

    # liquidity_constrained
    daily_volume = risk_params.get("daily_volume")
    max_vol_pct = risk_params.get("max_volume_pct", 0.1)
    if daily_volume is not None and daily_volume > 0:
        base = min(candidates_list) if candidates_list else 0
        lc = compute_liquidity_constrained_size(int(base), daily_volume, max_vol_pct)
        candidates_list.append(lc)

    min_shares = min(candidates_list) if candidates_list else 0
    amount = round(min_shares * price, 2)

    return {
        "shares": min_shares,
        "amount": amount,
        "method": "ladder",
    }


def compute_correlation_adjusted_size(
    position_sizes: dict[str, float],
    correlation_matrix: np.ndarray,
    max_correlation: float = 0.7,
) -> dict[str, float]:
    tickers = list(position_sizes.keys())
    n = len(tickers)
    if n == 0 or correlation_matrix.shape != (n, n):
        return dict(position_sizes)

    adjusted = {}
    for i, ticker in enumerate(tickers):
        excess = 0.0
        count = 0
        for j in range(n):
            if i != j:
                corr = correlation_matrix[i, j]
                if corr > max_correlation:
                    excess += corr - max_correlation
                    count += 1
        penalty = 1.0 / (1.0 + excess / count) if count > 0 else 1.0
        adjusted[ticker] = position_sizes[ticker] * penalty

    return adjusted


# ── RiskManager: unified pre-trade risk gate ──────────────────────────────────

_TradeCheckResult = tuple[bool, str]


class RiskManager:
    """Unified risk management gate that checks all controls before a trade.

    Usage:
        rm = RiskManager()
        ok, reason = await rm.can_trade(ticker="SBER", quantity=100, price=250.0, portfolio_value=500000)
        if not ok:
            logger.warning("Trade blocked: %s", reason)
    """

    def __init__(self) -> None:
        self._var_cache: dict[str, dict[str, float]] = {}
        self._sentiment_cache: dict[str, list[float]] = {}

    async def can_trade(
        self,
        ticker: str,
        quantity: int,
        price: float,
        portfolio_value: float = 0.0,
        direction: str = "BUY",
        is_short: bool = False,
    ) -> _TradeCheckResult:
        """Run all risk checks and return (allowed: bool, reason: str)."""
        checks = [
            self._check_kill_switch(),
            self._check_trading_enabled(),
        ]

        if portfolio_value > 0:
            checks.extend([
                self._check_position_size(quantity, price, portfolio_value),
                self._check_concentration(ticker, quantity, price, portfolio_value),
                self._check_var(ticker),
                self._check_daily_loss(portfolio_value),
                self._check_drawdown(portfolio_value),
            ])

        if is_short:
            checks.append(self._check_short_eligibility(ticker, quantity))

        checks.append(self._check_sentiment(ticker))

        for check_fn in checks:
            ok, reason = await check_fn
            if not ok:
                return False, reason

        return True, "All risk checks passed"

    async def _check_kill_switch(self) -> _TradeCheckResult:
        from src.trading.risk.guards import is_kill_switch_active

        if is_kill_switch_active():
            return False, "Kill switch is active — trading halted"
        return True, "Kill switch OK"

    async def _check_trading_enabled(self) -> _TradeCheckResult:
        from src.config import settings

        if not settings.enable_trading:
            return False, "Trading disabled via ENABLE_TRADING config"
        return True, "Trading enabled"

    async def _check_position_size(self, quantity: int, price: float, portfolio_value: float) -> _TradeCheckResult:
        from src.trading.risk.guards import check_position_size

        position_value = quantity * price
        ok, msg = check_position_size(position_value, portfolio_value)
        if not ok:
            return False, f"Position size limit: {msg}"
        return True, msg

    async def _check_concentration(self, ticker: str, quantity: int, price: float, portfolio_value: float) -> _TradeCheckResult:
        from src.trading.compliance.limits import check_position_limit

        position_pct = (quantity * price) / portfolio_value if portfolio_value > 0 else 0
        ok, msg = check_position_limit(ticker, position_pct)
        if not ok:
            return False, f"Concentration limit: {msg}"
        return True, msg

    async def _check_var(self, ticker: str) -> _TradeCheckResult:
        from src.trading.risk.guards import check_var_limit

        var_data = self._var_cache.get(ticker)
        if var_data is not None:
            var_95 = float(var_data.get("var_95", 0)) / 100
        else:
            var_data = await asyncio.to_thread(self._load_var_data, ticker)
            if var_data is not None:
                self._var_cache[ticker] = var_data
            var_95 = float(var_data.get("var_95", 0)) / 100 if var_data else 0.0

        ok, msg = check_var_limit(var_95)
        if not ok:
            return False, f"VaR limit: {msg}"
        return True, msg

    @staticmethod
    def _load_var_data(ticker: str) -> dict[str, float] | None:
        try:
            from src.db.connection import get_session
            from src.db.models.instrument import Instrument, Price

            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker).first()
                if inst:
                    prices_list = [
                        float(p.close) for p in db.query(Price)
                        .filter_by(instrument_id=int(inst.id))
                        .order_by(Price.date.desc())
                        .limit(100).all()
                        if p.close
                    ]
                    if len(prices_list) > 20:
                        return compute_var(prices_list)
                    return None
                return None
            finally:
                db.close()
        except Exception:
            return None

    async def _check_daily_loss(self, portfolio_value: float) -> _TradeCheckResult:
        from src.trading.risk.guards import check_daily_loss

        try:
            from src.trading.risk.guards import get_day_pnl

            _, pnl_pct = get_day_pnl()
            triggered = check_daily_loss(pnl_pct)
            if triggered:
                return False, f"Daily loss limit hit ({pnl_pct:.2%})"
            return True, f"Daily P&L: {pnl_pct:.2%}"
        except Exception:
            return True, "Daily loss check unavailable"

    async def _check_drawdown(self, portfolio_value: float) -> _TradeCheckResult:
        from src.trading.risk.guards import current_drawdown

        dd = current_drawdown()
        from src.trading.risk.guards import max_drawdown_pct
        limit = max_drawdown_pct()
        if abs(dd) > limit:
            return False, f"Max drawdown exceeded: {dd:.2%} > {limit:.2%}"
        return True, f"Drawdown: {dd:.2%} / {limit:.2%}"

    async def _check_short_eligibility(self, ticker: str, quantity: int) -> _TradeCheckResult:
        from src.trading.compliance.limits import check_short_eligibility

        ok, msg = check_short_eligibility(ticker, quantity)
        if not ok:
            return False, f"Short eligibility: {msg}"
        return True, msg

    async def _check_sentiment(self, ticker: str) -> _TradeCheckResult:
        from src.trading.risk.guards import check_news_sentiment

        scores = self._sentiment_cache.get(ticker)
        if scores is None:
            scores = await asyncio.to_thread(self._load_sentiment_scores, ticker)
            self._sentiment_cache[ticker] = scores

        ok, msg = check_news_sentiment(scores)
        if not ok:
            return False, f"Sentiment check: {msg}"
        return True, msg

    @staticmethod
    def _load_sentiment_scores(ticker: str) -> list[float]:
        try:
            from datetime import datetime, timedelta, timezone

            from src.db.connection import get_session
            from src.db.models import Instrument, News, NewsInstrument

            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker).first()
                if inst:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
                    news_list = (
                        db.query(News)
                        .join(NewsInstrument)
                        .filter(
                            NewsInstrument.instrument_id == int(inst.id),
                            News.published_at >= cutoff,
                            News.sentiment_score.isnot(None),
                        )
                        .all()
                    )
                    return [float(n.sentiment_score) for n in news_list if n.sentiment_score is not None]
                return []
            finally:
                db.close()
        except Exception:
            return []

    async def compute_position_size(
        self,
        capital: float,
        price: float,
        ticker: str = "",
        var_cache: dict[str, dict[str, float]] | None = None,
    ) -> int:
        """Compute safe position size considering volatility, VaR, and liquidity."""
        if var_cache:
            self._var_cache.update(var_cache)

        var_info = self._var_cache.get(ticker, {"var_95": 2.0})
        var_95 = float(var_info.get("var_95", 2.0))

        from src.trading.risk.guards import risk_per_trade
        risk_pt = risk_per_trade()

        sl_pct = min(5.0, max(1.0, var_95 * 3))
        pos = compute_vol_adjusted_size(capital, risk_pt, price * sl_pct / 100, price)

        avg_vol = await asyncio.to_thread(self._compute_liquidity, ticker)
        if avg_vol > 0:
            pos = compute_liquidity_constrained_size(pos, avg_vol)

        return max(pos, 1)

    @staticmethod
    def _compute_liquidity(ticker: str) -> float:
        try:
            import numpy as np

            from src.db.connection import get_session
            from src.db.models.instrument import Instrument, Price

            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker).first()
                if inst:
                    prices_list = [float(p.close) for p in db.query(Price).filter_by(instrument_id=int(inst.id)).order_by(Price.date.desc()).limit(20).all() if p.close]
                    if prices_list:
                        return float(np.mean(prices_list)) * 1000
                return 0.0
            finally:
                db.close()
        except Exception as e:
            logger.debug("Liquidity calc unavailable for %s: %s", ticker, e)
            return 0.0

    def invalidate_cache(self, ticker: str | None = None) -> None:
        if ticker:
            self._var_cache.pop(ticker, None)
            self._sentiment_cache.pop(ticker, None)
        else:
            self._var_cache.clear()
            self._sentiment_cache.clear()


_default_risk_manager: RiskManager | None = None


def get_risk_manager() -> RiskManager:
    global _default_risk_manager
    if _default_risk_manager is None:
        _default_risk_manager = RiskManager()
    return _default_risk_manager
