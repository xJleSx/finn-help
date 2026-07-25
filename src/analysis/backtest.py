import logging
from dataclasses import dataclass, field
from typing import Any, Optional, cast

import numpy as np

from src.analysis.metrics import compute_calmar, compute_max_drawdown, compute_sharpe, compute_sortino
from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.portfolio.allocator import allocator

logger = logging.getLogger(__name__)

SLIPPAGE_BPS = 5  # 0.05% slippage per trade
COMMISSION_PCT = 0.0004  # 0.04% broker commission
COMMISSION_FIXED = 0.0  # no fixed commission
REBALANCE_THRESHOLD = 0.05  # 5% drift triggers rebalance


@dataclass
class BacktestConfig:
    capital: float = 100_000
    lookback_days: int = 365
    slippage_bps: int = SLIPPAGE_BPS
    commission_pct: float = COMMISSION_PCT
    commission_fixed: float = COMMISSION_FIXED
    rebalance_threshold: float = REBALANCE_THRESHOLD
    regime_lookback: int = 21
    benchmark_ticker: str = "IMOEX"
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    rebalance_frequency_days: int = 0
    use_atr_sizing: bool = False
    atr_multiplier: float = 2.0
    max_positions: int = 8


@dataclass
class MonteCarloResult:
    simulations: int
    mean_return: float
    std_return: float
    var_95: float
    cvar_95: float
    upside_pct: float
    downside_pct: float
    best_return: float
    worst_return: float
    median_return: float


@dataclass
class RegimeInfo:
    regime: str  # BULL, BEAR, SIDEWAYS, HIGH_VOL
    volatility: float
    trend_strength: float
    avg_return: float


@dataclass
class BacktestResult:
    capital: float
    config: BacktestConfig = field(default_factory=BacktestConfig)
    positions: list[dict[str, Any]] = field(default_factory=list)
    portfolio_returns: list[float] = field(default_factory=list)
    benchmark_returns: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    trades: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    monte_carlo: Optional[MonteCarloResult] = None
    regime: Optional[RegimeInfo] = None

    def add_snapshot(self, date_str: str, port_ret: float, bench_ret: float) -> None:
        self.dates.append(date_str)
        self.portfolio_returns.append(port_ret)
        self.benchmark_returns.append(bench_ret)

    @property
    def portfolio_return(self) -> float:
        if not self.portfolio_returns:
            return 0.0
        return float(np.prod([1 + r for r in self.portfolio_returns]) - 1)

    @property
    def benchmark_return(self) -> float:
        if not self.benchmark_returns:
            return 0.0
        return float(np.prod([1 + r for r in self.benchmark_returns]) - 1)

    @property
    def alpha(self) -> float:
        return self.portfolio_return - self.benchmark_return

    @property
    def portfolio_sharpe(self) -> float:
        return compute_sharpe(np.array(self.portfolio_returns))

    @property
    def portfolio_sortino(self) -> float:
        return compute_sortino(np.array(self.portfolio_returns))

    @property
    def portfolio_max_dd(self) -> float:
        if not self.portfolio_returns:
            return 0.0
        cumulative = np.cumprod([1 + r for r in self.portfolio_returns])
        return compute_max_drawdown(cumulative.tolist())

    @property
    def portfolio_calmar(self) -> float:
        return compute_calmar(np.array(self.portfolio_returns), np.cumprod([1 + r for r in self.portfolio_returns]).tolist())

    @property
    def win_rate(self) -> float:
        if not self.portfolio_returns:
            return 0.0
        wins = sum(1 for r in self.portfolio_returns if r > 0)
        return wins / len(self.portfolio_returns)

    @property
    def avg_win(self) -> float:
        wins = [r for r in self.portfolio_returns if r > 0]
        return float(np.mean(wins)) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [r for r in self.portfolio_returns if r < 0]
        return float(np.mean(losses)) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        wins = sum(r for r in self.portfolio_returns if r > 0)
        losses = abs(sum(r for r in self.portfolio_returns if r < 0))
        return wins / losses if losses > 0 else float("inf")

    def summary(self) -> str:
        text = (
            f"📊 *Результат бэктеста*\n\n"
            f"💰 Капитал: {self.capital:,.0f} ₽\n"
            f"📈 Доходность портфеля: {self.portfolio_return:+.1%}\n"
            f"📉 Доходность бенчмарка: {self.benchmark_return:+.1%}\n"
            f"🏆 Альфа: {self.alpha:+.1%}\n\n"
            f"⚙ Sharpe: {self.portfolio_sharpe:.2f}\n"
            f"⚙ Sortino: {self.portfolio_sortino:.2f}\n"
            f"⚙ Calmar: {self.portfolio_calmar:.2f}\n"
            f"⚠️ Макс. просадка: {self.portfolio_max_dd:.1%}\n"
            f"📊 Периодов: {len(self.dates)}\n"
            f"🎯 Win Rate: {self.win_rate:.1%}\n"
            f"📈 Фактор прибыли: {self.profit_factor:.2f}\n"
            f"💸 Комиссии: {self.total_commission:,.0f} ₽\n"
            f"⚡ Проскальзывание: {self.total_slippage:,.0f} ₽\n"
        )
        if self.monte_carlo:
            text += (
                f"\n🎲 *Monte-Carlo ({self.monte_carlo.simulations} симуляций)*\n"
                f"📊 Средняя: {self.monte_carlo.mean_return:+.1%}\n"
                f"📊 Медианная: {self.monte_carlo.median_return:+.1%}\n"
                f"📈 Лучшая: {self.monte_carlo.best_return:+.1%}\n"
                f"📉 Худшая: {self.monte_carlo.worst_return:+.1%}\n"
                f"🟢 Доля успеха: {self.monte_carlo.upside_pct:.1%}\n"
                f"🔴 VaR(95%): {self.monte_carlo.var_95:.1%}\n"
                f"🔴 CVaR(95%): {self.monte_carlo.cvar_95:.1%}\n"
            )
        if self.regime:
            text += f"\n🌡 Режим рынка: {self.regime.regime}\n"
        return text


def detect_regime(returns: np.ndarray, lookback: int = 21) -> RegimeInfo:
    if len(returns) < lookback:
        return RegimeInfo(regime="UNKNOWN", volatility=0.0, trend_strength=0.0, avg_return=0.0)
    recent = returns[-lookback:]
    vol = float(np.std(recent))
    avg_ret = float(np.mean(recent))
    cum_ret = float(np.prod(1 + recent) - 1)
    annual_vol = vol * np.sqrt(252)
    trend_strength = abs(cum_ret) / (annual_vol * np.sqrt(lookback / 252) + 1e-8)
    if annual_vol > 0.4:
        regime = "HIGH_VOL"
    elif cum_ret > 0.05 and trend_strength > 0.5:
        regime = "BULL"
    elif cum_ret < -0.05 and trend_strength > 0.5:
        regime = "BEAR"
    else:
        regime = "SIDEWAYS"
    return RegimeInfo(regime=regime, volatility=vol, trend_strength=trend_strength, avg_return=avg_ret)


def run_monte_carlo(returns: list[float], n_simulations: int = 1000, periods: int = 252) -> MonteCarloResult:
    if len(returns) < 10:
        return MonteCarloResult(
            simulations=0,
            mean_return=0.0,
            std_return=0.0,
            var_95=0.0,
            cvar_95=0.0,
            upside_pct=0.0,
            downside_pct=0.0,
            best_return=0.0,
            worst_return=0.0,
            median_return=0.0,
        )
    arr = np.array(returns)
    rng = np.random.default_rng(42)
    results = []
    for _ in range(n_simulations):
        sampled = rng.choice(arr, size=periods, replace=True)
        total = float(np.prod(1 + sampled) - 1)
        results.append(total)
    results_arr = np.array(results)
    results_arr.sort()
    return MonteCarloResult(
        simulations=n_simulations,
        mean_return=float(np.mean(results_arr)),
        std_return=float(np.std(results_arr)),
        var_95=float(np.percentile(results_arr, 5)),
        cvar_95=float(np.mean(results_arr[results_arr <= np.percentile(results_arr, 5)])),
        upside_pct=float(np.mean(results_arr > 0)),
        downside_pct=float(np.mean(results_arr < 0)),
        best_return=float(results_arr[-1]),
        worst_return=float(results_arr[0]),
        median_return=float(np.median(results_arr)),
    )


def apply_costs(
    gross_return: float,
    is_rebalance: bool,
    position_weight: float,
    config: BacktestConfig,
) -> tuple[float, float, float]:
    slippage_cost = 0.0
    commission_cost = 0.0
    if is_rebalance:
        turnover = position_weight
        slippage_cost = turnover * (config.slippage_bps / 10_000)
        commission_cost = abs(gross_return) * config.commission_pct + config.commission_fixed
    net_return = gross_return - slippage_cost - commission_cost
    return net_return, slippage_cost, commission_cost


def _compute_atr(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 0.0
    tr_values = []
    for i in range(1, len(prices)):
        high = max(prices[i], prices[i - 1])
        low = min(prices[i], prices[i - 1])
        tr = high - low
        tr_values.append(tr)
    if not tr_values:
        return 0.0
    return float(np.mean(tr_values[-period:]))


def _check_stop_take(
    current_price: float,
    entry_price: float,
    high: float,
    low: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> str | None:
    pnl_pct = (current_price - entry_price) / entry_price
    if pnl_pct <= -stop_loss_pct:
        return "stop_loss"
    if pnl_pct >= take_profit_pct:
        return "take_profit"
    daily_high_pnl = (high - entry_price) / entry_price
    daily_low_pnl = (low - entry_price) / entry_price
    if daily_low_pnl <= -stop_loss_pct:
        return "stop_loss"
    if daily_high_pnl >= take_profit_pct:
        return "take_profit"
    return None


def backtest_allocation(
    capital: float = 100_000,
    lookback_days: int = 365,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    if config is None:
        config = BacktestConfig(capital=capital, lookback_days=lookback_days)
    db = get_session()
    try:
        picks = allocator.recommend(capital=capital)
        result = BacktestResult(capital=capital, config=config)

        has_bonds = any(
            db.query(Instrument.instrument_type).filter(Instrument.id == p["id"]).scalar() == "bond"
            for p in picks[: config.max_positions]
        )
        bt = "RGBITR" if has_bonds else config.benchmark_ticker

        benchmark_prices = (
            db.query(Price).join(Instrument).filter(Instrument.ticker == bt).order_by(Price.date.desc()).limit(lookback_days + 10).all()
        )
        if not benchmark_prices:
            benchmark_prices = (
                db.query(Price).join(Instrument).filter(Instrument.ticker == "IMOEX").order_by(Price.date.desc()).limit(lookback_days + 10).all()
            )
        benchmark_vals = [cast(float, p.close) for p in reversed(benchmark_prices) if p.close]

        result.positions = picks[: config.max_positions]
        portfolio_prices: dict[str, list[float]] = {}
        portfolio_highs: dict[str, list[float]] = {}
        portfolio_lows: dict[str, list[float]] = {}
        for p in result.positions:
            prices = (
                db.query(Price)
                .filter_by(instrument_id=p["id"])
                .order_by(Price.date.desc())
                .limit(lookback_days + 10)
                .all()
            )
            vals = [cast(float, x.close) for x in reversed(prices) if x.close]
            highs = [cast(float, x.high) for x in reversed(prices) if x.high]
            lows = [cast(float, x.low) for x in reversed(prices) if x.low]
            if vals:
                portfolio_prices[p["ticker"]] = vals
                portfolio_highs[p["ticker"]] = highs if len(highs) == len(vals) else vals
                portfolio_lows[p["ticker"]] = lows if len(lows) == len(vals) else vals

        if not portfolio_prices or len(benchmark_vals) < 20:
            logger.warning("Not enough historical data for backtest")
            return result

        min_len = min(len(v) for v in portfolio_prices.values())
        min_len = min(min_len, len(benchmark_vals))

        tickers_with_prices = [p["ticker"] for p in result.positions if p["ticker"] in portfolio_prices]

        weights = [p.get("score", 1) for p in result.positions if p["ticker"] in portfolio_prices]
        total_w = sum(weights) or 1
        weights = [w / total_w for w in weights]
        weight_map: dict[str, float] = dict(zip(tickers_with_prices, weights))

        entry_prices: dict[str, float] = {}
        stopped_out: dict[str, bool] = {}
        last_rebalance_day = 0

        for p in result.positions:
            t = p["ticker"]
            if t in portfolio_prices and portfolio_prices[t]:
                entry_prices[t] = portfolio_prices[t][0]
                stopped_out[t] = False

        for i in range(1, min_len):
            port_ret = 0.0
            total_slippage = 0.0
            total_commission = 0.0

            should_rebalance = False

            if config.rebalance_frequency_days > 0 and (i - last_rebalance_day) >= config.rebalance_frequency_days:
                should_rebalance = True

            for ticker in tickers_with_prices:
                if stopped_out.get(ticker, False):
                    continue
                vals = portfolio_prices[ticker]
                if i >= len(vals):
                    continue
                high = portfolio_highs.get(ticker, vals)[i]
                low = portfolio_lows.get(ticker, vals)[i]
                prev_close = vals[i - 1]
                curr_close = vals[i]
                gross_ret = (curr_close - prev_close) / prev_close

                ep = entry_prices.get(ticker, vals[0])
                sl_result = _check_stop_take(curr_close, ep, high, low, config.stop_loss_pct, config.take_profit_pct)
                if sl_result is not None:
                    stopped_out[ticker] = True
                    gross_ret = min(gross_ret, 0.0) if sl_result == "stop_loss" else max(gross_ret, 0.0)
                    should_rebalance = True

                w = weight_map.get(ticker, 0.0)
                net_ret, slip, comm = apply_costs(
                    gross_ret * w,
                    is_rebalance=False,
                    position_weight=w,
                    config=config,
                )
                port_ret += net_ret
                total_slippage += slip
                total_commission += comm

                if not should_rebalance and config.rebalance_threshold > 0:
                    pnl_pct = (curr_close - ep) / ep if ep > 0 else 0.0
                    if abs(pnl_pct * w) > config.rebalance_threshold:
                        should_rebalance = True

            if should_rebalance and i > 1:
                active_picks = allocator.recommend(capital=capital)
                new_weights = {}
                for p2 in active_picks[: config.max_positions]:
                    t2 = p2["ticker"]
                    if t2 in portfolio_prices and t2 not in stopped_out:
                        new_weights[t2] = p2.get("score", 1)
                    elif t2 in portfolio_prices and stopped_out.get(t2, False):
                        pass

                if new_weights:
                    existing = [t for t in tickers_with_prices if not stopped_out.get(t, False)]
                    combined = existing + [t for t in new_weights if t not in existing]

                    if config.use_atr_sizing and i > 20:
                        atr_inv: dict[str, float] = {}
                        for t in combined:
                            vals = portfolio_prices.get(t, [])
                            if len(vals) >= 20:
                                atr_val = _compute_atr(vals[:i], period=14)
                                atr_inv[t] = 1.0 / (atr_val + 1e-8)
                            else:
                                atr_inv[t] = 1.0
                        atr_total = sum(atr_inv.get(t, 1.0) for t in combined) or 1.0
                        atr_weights = [atr_inv.get(t, 1.0) / atr_total for t in combined]
                    else:
                        atr_weights = None

                    rebal_weights = []
                    for idx, t in enumerate(combined):
                        base_w = new_weights.get(t, 0.0)
                        if config.use_atr_sizing and atr_weights is not None:
                            base_w *= atr_weights[idx] * len(combined)
                        rebal_weights.append(base_w)
                    total_rw = sum(rebal_weights) or 1
                    rebal_weights = [w / total_rw for w in rebal_weights]
                    weight_map = dict(zip(combined, rebal_weights))
                    for t in combined:
                        if t in portfolio_prices and portfolio_prices[t]:
                            entry_prices[t] = portfolio_prices[t][i]
                            stopped_out[t] = False

                    slippage_cost = sum(w * (config.slippage_bps / 10_000) for w in rebal_weights)
                    comm_cost = config.commission_pct * len(rebal_weights) + config.commission_fixed
                    port_ret -= slippage_cost
                    port_ret -= comm_cost / capital
                    total_slippage += slippage_cost
                    total_commission += comm_cost / capital
                    result.trades += sum(1 for w in rebal_weights if w > 0)
                    last_rebalance_day = i

            bench_ret = (benchmark_vals[i] - benchmark_vals[i - 1]) / benchmark_vals[i - 1]
            result.add_snapshot(str(i), port_ret, bench_ret)
            result.total_slippage += total_slippage * capital
            result.total_commission += total_commission * capital

        mc = run_monte_carlo(result.portfolio_returns)
        result.monte_carlo = mc

        bench_prices = np.array(benchmark_vals[:min_len])
        bench_returns = (bench_prices[1:] - bench_prices[:-1]) / bench_prices[:-1]
        result.regime = detect_regime(bench_returns)

        return result
    finally:
        db.close()
