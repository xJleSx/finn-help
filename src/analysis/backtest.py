import logging
import random
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, cast

import numpy as np

from src.analysis.metrics import compute_calmar, compute_max_drawdown, compute_sharpe, compute_sortino
from src.config import DEFAULT_PROBABILITY_BY_RATING
from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.portfolio.allocator import allocator

logger = logging.getLogger(__name__)

SLIPPAGE_BPS = 5  # 0.05% slippage per trade
COMMISSION_PCT = 0.0004  # 0.04% broker commission
COMMISSION_FIXED = 0.0  # no fixed commission
REBALANCE_THRESHOLD = 0.05  # 5% drift triggers rebalance

MONTHLY_CPI: dict[str, float] = {
    "2024-01": 0.074, "2024-02": 0.076, "2024-03": 0.077,
    "2024-04": 0.078, "2024-05": 0.081, "2024-06": 0.084,
    "2024-07": 0.086, "2024-08": 0.087, "2024-09": 0.088,
    "2024-10": 0.086, "2024-11": 0.085, "2024-12": 0.083,
    "2025-01": 0.091, "2025-02": 0.095, "2025-03": 0.098,
    "2025-04": 0.099, "2025-05": 0.098, "2025-06": 0.097,
    "2025-07": 0.096, "2025-08": 0.095, "2025-09": 0.093,
    "2025-10": 0.091, "2025-11": 0.089, "2025-12": 0.088,
    "2026-01": 0.088, "2026-02": 0.089, "2026-03": 0.090,
    "2026-04": 0.091, "2026-05": 0.090, "2026-06": 0.089,
    "2026-07": 0.088,
}


def _cpi_for_month(year: int, month: int) -> float:
    key = f"{year:04d}-{month:02d}"
    return MONTHLY_CPI.get(key, 0.08)


def real_return_adjustment(nominal_return: float, start_date: date, end_date: date) -> float:
    cpi_start = _cpi_for_month(start_date.year, start_date.month)
    cpi_end = _cpi_for_month(end_date.year, end_date.month)
    inflation_factor = (1 + cpi_end) / (1 + cpi_start)
    return (1 + nominal_return) / inflation_factor - 1


DEFAULTED_BONDS_SYNTHETIC: list[dict[str, Any]] = [
    {"ticker": "RU000A1066A4", "default_date": "2024-03-15", "recovery": 0.25, "rating": "BB", "sector": "retail"},
    {"ticker": "RU000A105Y89", "default_date": "2024-06-01", "recovery": 0.30, "rating": "B", "sector": "construction"},
    {"ticker": "RU000A1067A3", "default_date": "2024-09-10", "recovery": 0.20, "rating": "CCC", "sector": "retail"},
    {"ticker": "RU000A1068A2", "default_date": "2025-01-20", "recovery": 0.35, "rating": "BB+", "sector": "real_estate"},
]


def inject_synthetic_defaults(
    positions: list[dict[str, Any]],
    current_date: date,
    rating_field: str = "rating",
) -> list[dict[str, Any]]:
    result = list(positions)
    for i, pos in enumerate(positions):
        rating = (pos.get(rating_field) or "NR").upper()
        p_default = 1.0 - DEFAULT_PROBABILITY_BY_RATING.get(rating, 0.90)
        if random.random() < p_default:  # noqa: S311
            recovery = 0.35
            result[i] = dict(pos)
            result[i]["defaulted"] = True
            result[i]["recoveryRate"] = recovery
            result[i]["value"] = pos.get("value", 0) * recovery
            logger.info("Synthetic default injected for %s (rating=%s, recovery=%.0f%%)", pos.get("ticker", "?"), rating, recovery * 100)
    return result


def bond_stop_loss_trigger(
    ticker: str,
    current_price: float,
    entry_price: float,
    current_ytm: Optional[float] = None,
    entry_ytm: Optional[float] = None,
    rating_downgrade: int = 0,
    instrument_type: str = "stock",
) -> Optional[str]:
    if instrument_type != "bond":
        pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0
        if pnl_pct <= -0.05:
            return "stop_loss"
        if pnl_pct >= 0.10:
            return "take_profit"
        return None

    price_drop = (current_price - entry_price) / entry_price if entry_price > 0 else 0

    if rating_downgrade >= 2:
        return "rating_downgrade"

    if price_drop < -0.15:
        ytm_change = (current_ytm or 0) - (entry_ytm or 0)
        if ytm_change < 0.01:
            return "default_risk_stop"

    return None


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
    _start_date: Optional[date] = None
    _end_date: Optional[date] = None

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

    @property
    def inflation_adjusted_return(self) -> float:
        ret = self.portfolio_return
        if not self._start_date or not self._end_date:
            return ret
        return real_return_adjustment(ret, self._start_date, self._end_date)

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
            f"📊 Реальная доходность (с поправкой на инфляцию): {self.inflation_adjusted_return:+.1%}\n"
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
    import asyncio

    if config is None:
        config = BacktestConfig(capital=capital, lookback_days=lookback_days)
    db = get_session()
    try:
        picks = asyncio.run(allocator.recommend(capital=capital))
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
        for p in result.positions:
            prices = (
                db.query(Price)
                .filter_by(instrument_id=p["id"])
                .order_by(Price.date.desc())
                .limit(lookback_days + 10)
                .all()
            )
            vals = [cast(float, x.close) for x in reversed(prices) if x.close]
            if vals:
                portfolio_prices[p["ticker"]] = vals

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
        defaulted_bonds: dict[str, float] = {}
        entry_ytm: dict[str, float] = {}
        start_date: Optional[date] = None

        for p in result.positions:
            t = p["ticker"]
            if t in portfolio_prices and portfolio_prices[t]:
                entry_prices[t] = portfolio_prices[t][0]
                stopped_out[t] = False
                entry_ytm[t] = p.get("ytm", 0.0)

        position_instrument_types: dict[str, str] = {}
        for p in result.positions:
            t = p["ticker"]
            inst = db.query(Instrument.instrument_type).filter(Instrument.id == p["id"]).scalar()
            position_instrument_types[t] = inst or "stock"

        for i in range(1, min_len):
            port_ret = 0.0
            total_slippage = 0.0
            total_commission = 0.0

            should_rebalance = False

            if config.rebalance_frequency_days > 0 and (i - last_rebalance_day) >= config.rebalance_frequency_days:
                should_rebalance = True

            if start_date is None:
                price_rec = db.query(Price).join(Instrument).filter(Instrument.ticker.in_(tickers_with_prices)).first()
                if price_rec:
                    start_date = price_rec.date
                    if isinstance(start_date, str):
                        from datetime import datetime as dt
                        start_date = dt.strptime(start_date, "%Y-%m-%d").date()

            current_positions = []
            for ticker in tickers_with_prices:
                if stopped_out.get(ticker, False):
                    continue
                if ticker in defaulted_bonds:
                    continue
                vals = portfolio_prices[ticker]
                if i >= len(vals):
                    continue
                current_positions.append({
                    "ticker": ticker,
                    "value": vals[i] * weight_map.get(ticker, 0),
                    "rating": next((p.get("rating", "NR") for p in result.positions if p["ticker"] == ticker), "NR"),
                })

            updated_positions = inject_synthetic_defaults(current_positions, start_date or date.today())
            for up in updated_positions:
                if up.get("defaulted"):
                    defaulted_bonds[up["ticker"]] = up.get("recoveryRate", 0.35)
                    weight_map[up["ticker"]] = 0.0
                    logger.info("Synthetic default for %s, removed from portfolio", up["ticker"])

            for ticker in tickers_with_prices:
                if stopped_out.get(ticker, False):
                    continue
                if ticker in defaulted_bonds:
                    continue
                vals = portfolio_prices[ticker]
                if i >= len(vals):
                    continue
                prev_close = vals[i - 1]
                curr_close = vals[i]
                gross_ret = (curr_close - prev_close) / prev_close

                ep = entry_prices.get(ticker, vals[0])
                inst_type = position_instrument_types.get(ticker, "stock")
                rating_change = 0
                sl_result = bond_stop_loss_trigger(
                    ticker=ticker,
                    current_price=curr_close,
                    entry_price=ep,
                    current_ytm=entry_ytm.get(ticker),
                    entry_ytm=entry_ytm.get(ticker),
                    rating_downgrade=rating_change,
                    instrument_type=inst_type,
                )
                if sl_result is not None:
                    stopped_out[ticker] = True
                    gross_ret = min(gross_ret, 0.0) if sl_result in ("stop_loss", "default_risk_stop") else max(gross_ret, 0.0)
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
                active_picks = asyncio.run(allocator.recommend(capital=capital))
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

        end_date = start_date
        if result.dates:
            try:
                from datetime import datetime as dt
                last_idx = int(result.dates[-1])
                if price_rec:
                    end_date = price_rec.date
                    if isinstance(end_date, str):
                        end_date = dt.strptime(end_date, "%Y-%m-%d").date()
                    from datetime import timedelta
                    end_date = end_date + timedelta(days=last_idx)
            except (ValueError, TypeError):
                pass
        result._start_date = start_date
        result._end_date = end_date

        return result
    finally:
        db.close()
