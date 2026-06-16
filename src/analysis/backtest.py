import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.portfolio.allocator import allocator

logger = logging.getLogger(__name__)

SLIPPAGE_BPS = 5  # 0.05% slippage per trade
COMMISSION_PCT = 0.0004  # 0.04% broker commission
COMMISSION_FIXED = 0.0  # no fixed commission
REBALANCE_THRESHOLD = 0.05  # 5% drift triggers rebalance


def _returns(prices: list[float]) -> np.ndarray:
    arr = np.array(prices, dtype=float)
    return np.diff(arr) / arr[:-1]


def _sharpe(returns: np.ndarray, annual_factor: int = 252) -> float:
    if len(returns) < 5 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(annual_factor))


def _max_drawdown(prices: list[float]) -> float:
    arr = np.array(prices)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))


def _sortino(returns: np.ndarray, annual_factor: int = 252) -> float:
    if len(returns) < 5:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(downside) * np.sqrt(annual_factor))


def _calmar(returns: np.ndarray, prices: list[float]) -> float:
    dd = _max_drawdown(prices)
    if dd == 0:
        return 0.0
    total_ret = float(np.prod(1 + returns)) - 1
    return total_ret / abs(dd)


@dataclass
class BacktestConfig:
    capital: float = 100_000
    lookback_days: int = 365
    slippage_bps: int = SLIPPAGE_BPS
    commission_pct: float = COMMISSION_PCT
    commission_fixed: float = COMMISSION_FIXED
    rebalance_threshold: float = REBALANCE_THRESHOLD
    regime_lookback: int = 21


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
    positions: list[dict] = field(default_factory=list)
    portfolio_returns: list[float] = field(default_factory=list)
    benchmark_returns: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    trades: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    monte_carlo: Optional[MonteCarloResult] = None
    regime: Optional[RegimeInfo] = None

    def add_snapshot(self, date_str: str, port_ret: float, bench_ret: float):
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
        return _sharpe(np.array(self.portfolio_returns))

    @property
    def portfolio_sortino(self) -> float:
        return _sortino(np.array(self.portfolio_returns))

    @property
    def portfolio_max_dd(self) -> float:
        if not self.portfolio_returns:
            return 0.0
        cumulative = np.cumprod([1 + r for r in self.portfolio_returns])
        return _max_drawdown(cumulative.tolist())

    @property
    def portfolio_calmar(self) -> float:
        return _calmar(np.array(self.portfolio_returns), np.cumprod([1 + r for r in self.portfolio_returns]).tolist())

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
            f"📉 Доходность IMOEX: {self.benchmark_return:+.1%}\n"
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

        imoex_prices = (
            db.query(Price)
            .join(Instrument)
            .filter(Instrument.ticker == "IMOEX")
            .order_by(Price.date.desc())
            .limit(lookback_days + 10)
            .all()
        )
        imoex_vals = [p.close for p in reversed(imoex_prices) if p.close]

        result.positions = picks[:8]
        portfolio_prices: dict[str, list[float]] = {}
        for p in result.positions:
            prices = (
                db.query(Price)
                .filter_by(instrument_id=p["id"])
                .order_by(Price.date.desc())
                .limit(lookback_days + 10)
                .all()
            )
            vals = [x.close for x in reversed(prices) if x.close]
            if vals:
                portfolio_prices[p["ticker"]] = vals

        if not portfolio_prices or len(imoex_vals) < 20:
            logger.warning("Not enough historical data for backtest")
            return result

        min_len = min(len(v) for v in portfolio_prices.values())
        min_len = min(min_len, len(imoex_vals))

        weights = [p.get("score", 1) for p in result.positions if p["ticker"] in portfolio_prices]
        total_w = sum(weights) or 1
        weights = [w / total_w for w in weights]
        tickers_with_prices = [p["ticker"] for p in result.positions if p["ticker"] in portfolio_prices]

        for i in range(1, min_len):
            port_ret = 0.0
            total_slippage = 0.0
            total_commission = 0.0
            for idx, ticker in enumerate(tickers_with_prices):
                vals = portfolio_prices[ticker]
                if i < len(vals):
                    gross_ret = (vals[i] - vals[i - 1]) / vals[i - 1]
                    is_first_day = i == 1
                    net_ret, slip, comm = apply_costs(
                        gross_ret * weights[idx],
                        is_rebalance=is_first_day,
                        position_weight=weights[idx],
                        config=config,
                    )
                    port_ret += net_ret
                    total_slippage += slip
                    total_commission += comm

            bench_ret = (imoex_vals[i] - imoex_vals[i - 1]) / imoex_vals[i - 1]
            result.add_snapshot(str(i), port_ret, bench_ret)
            result.total_slippage += total_slippage * capital
            result.total_commission += total_commission * capital

        result.trades = len(tickers_with_prices)

        mc = run_monte_carlo(result.portfolio_returns)
        result.monte_carlo = mc

        regime = detect_regime(np.array(imoex_vals))
        result.regime = regime

        return result
    finally:
        db.close()
