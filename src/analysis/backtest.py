import logging

import numpy as np

from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.portfolio.allocator import allocator

logger = logging.getLogger(__name__)


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


class BacktestResult:
    def __init__(self, capital: float):
        self.capital = capital
        self.positions: list[dict] = []
        self.portfolio_returns: list[float] = []
        self.benchmark_returns: list[float] = []
        self.dates: list[str] = []

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

    def summary(self) -> str:
        text = (
            f"📊 *Результат бэктеста*\n\n"
            f"💰 Капитал: {self.capital:,.0f} ₽\n"
            f"📈 Доходность портфеля: {self.portfolio_return:+.1%}\n"
            f"📉 Доходность IMOEX: {self.benchmark_return:+.1%}\n"
            f"🏆 Альфа: {self.portfolio_return - self.benchmark_return:+.1%}\n\n"
            f"⚙ Sharpe: {self.portfolio_sharpe:.2f}\n"
            f"⚙ Sortino: {self.portfolio_sortino:.2f}\n"
            f"⚠️ Макс. просадка: {self.portfolio_max_dd:.1%}\n"
            f"📊 Периодов: {len(self.dates)}\n"
        )
        return text


def backtest_allocation(
    capital: float = 100_000,
    lookback_days: int = 365,
) -> BacktestResult:
    db = get_session()
    try:
        picks = allocator.recommend(capital=capital)
        result = BacktestResult(capital)

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
            for idx, ticker in enumerate(tickers_with_prices):
                vals = portfolio_prices[ticker]
                if i < len(vals):
                    ret = (vals[i] - vals[i - 1]) / vals[i - 1]
                    port_ret += ret * weights[idx]

            bench_ret = (imoex_vals[i] - imoex_vals[i - 1]) / imoex_vals[i - 1]
            result.add_snapshot(str(i), port_ret, bench_ret)

        return result
    finally:
        db.close()
