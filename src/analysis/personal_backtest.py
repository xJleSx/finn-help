import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional, cast

import numpy as np

from src.config import personal
from src.db.connection import get_session
from src.db.models import Instrument, Price

logger = logging.getLogger(__name__)

BT = personal.get("backtest", {})


@dataclass
class TradeRecord:
    date: date
    ticker: str
    action: str  # BUY | SELL
    price: float
    shares: float
    value: float
    commission: float
    slippage: float


@dataclass
class WalkForwardFold:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    portfolio_return: float
    benchmark_return: float
    sharpe: float
    max_drawdown: float
    trades: int


@dataclass
class PersonalBacktestResult:
    tickers: list[str]
    start_date: date
    end_date: date
    initial_capital: float
    final_capital: float
    total_return: float
    benchmark_return: float
    alpha: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_commission: float
    total_slippage: float
    n_trades: int
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    monthly_returns: list[dict[str, Any]] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    walk_forward: list[WalkForwardFold] = field(default_factory=list)
    benchmark_ticker: str = "IMOEX"

    def summary(self) -> str:
        lines = [
            f"📊 *Персональный бэктест ({self.start_date} — {self.end_date})*",
            "",
            f"💰 Начальный капитал: {self.initial_capital:,.0f} ₽",
            f"💰 Конечный капитал: {self.final_capital:,.0f} ₽",
            f"📈 Доходность: {self.total_return:+.1%}",
            f"📉 {self.benchmark_ticker}: {self.benchmark_return:+.1%}",
            f"🏆 Альфа: {self.alpha:+.1%}",
            "",
            f"⚙ Sharpe: {self.sharpe:.2f}",
            f"⚙ Sortino: {self.sortino:.2f}",
            f"⚙ Calmar: {self.calmar:.2f}",
            f"⚠️ Макс. просадка: {self.max_drawdown:.1%}",
            f"🎯 Win Rate: {self.win_rate:.1%}",
            f"📈 Фактор прибыли: {self.profit_factor:.2f}",
            f"💸 Комиссии: {self.total_commission:,.0f} ₽",
            f"⚡ Проскальзывание: {self.total_slippage:,.0f} ₽",
            f"🔄 Сделок: {self.n_trades}",
        ]
        if self.walk_forward:
            wf_returns = [f.portfolio_return for f in self.walk_forward]
            lines.extend(
                [
                    "",
                    "🔁 *Walk-Forward*",
                    f"   Фолдов: {len(self.walk_forward)}",
                    f"   Средняя доходность: {np.mean(wf_returns):+.1%}",
                    f"   Мин: {min(wf_returns):+.1%}",
                    f"   Макс: {max(wf_returns):+.1%}",
                    f"   Стабильность: {np.std(wf_returns):.2%}",
                ]
            )
        return "\n".join(lines)


def _prices_for_ticker(db: Any, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
    rows = (
        db.query(Price)
        .join(Instrument)
        .filter(Instrument.ticker == ticker, Price.date >= start, Price.date <= end)
        .order_by(Price.date)
        .all()
    )
    return [{"date": r.date, "close": r.close} for r in rows if r.close]


def _returns(arr: list[float]) -> np.ndarray:
    a = np.array(arr, dtype=float)
    return np.diff(a) / a[:-1]  # type: ignore[no-any-return]


def _sharpe(returns: np.ndarray, annual: int = 252) -> float:
    if len(returns) < 5 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(annual))


def _sortino(returns: np.ndarray, annual: int = 252) -> float:
    if len(returns) < 5:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(downside) * np.sqrt(annual))


def _max_dd(values: list[float]) -> float:
    arr = np.array(values)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))


def _calmar(returns: np.ndarray, prices: list[float]) -> float:
    dd = _max_dd(prices)
    if dd == 0:
        return 0.0
    total = float(np.prod(1 + returns)) - 1
    return total / abs(dd)


def run_personal_backtest(
    tickers: Optional[list[str]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    capital: Optional[float] = None,
    commission_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
    tax_rate: Optional[float] = None,
    use_tbank_fees: bool = False,
) -> PersonalBacktestResult:
    bt: dict[str, Any] = cast(dict[str, Any], personal.get("backtest", {}))
    tickers = tickers or cast(list[str], personal.get("favorite_tickers", ["SBER", "LKOH", "GAZP"]))
    start = start or date.fromisoformat(cast(str, bt.get("start_date", "2022-01-01")))
    end = end or date.fromisoformat(cast(str, bt.get("end_date", "2026-06-16")))
    capital = capital or cast(float, bt.get("initial_capital", 100_000.0))

    if use_tbank_fees:
        # T-Bank fees: 0.3% per trade + exchange fee 0.01%
        commission_pct = commission_pct or 0.003 + 0.0001
        slippage_pct = slippage_pct or 0.001
        tax_rate = tax_rate or 0.13
    else:
        commission_pct = commission_pct or cast(float, bt.get("commission_pct", 0.05)) / 100
        slippage_pct = slippage_pct or cast(float, bt.get("slippage_pct", 0.02)) / 100
        tax_rate = tax_rate or cast(float, bt.get("tax_rate", 0.13))
    benchmark = cast(str, bt.get("benchmark_ticker", "IMOEX"))

    db = get_session()
    try:
        # prices
        prices_map: dict[str, list[dict[str, Any]]] = {}
        for t in tickers:
            prices_map[t] = _prices_for_ticker(db, t, start, end)
        bench_prices = _prices_for_ticker(db, benchmark, start, end)

        valid_tickers = [t for t in tickers if len(prices_map.get(t, [])) > 20]
        if not valid_tickers or len(bench_prices) < 20:
            logger.warning("Not enough price data for backtest tickers=%s", valid_tickers)
            return PersonalBacktestResult(
                tickers=tickers,
                start_date=start,
                end_date=end,
                initial_capital=capital,
                final_capital=capital,
                total_return=0.0,
                benchmark_return=0.0,
                alpha=0.0,
                sharpe=0.0,
                sortino=0.0,
                calmar=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                total_commission=0.0,
                total_slippage=0.0,
                n_trades=0,
            )

        # align lengths
        min_len = min(len(prices_map[t]) for t in valid_tickers)
        min_len = min(min_len, len(bench_prices))
        for t in valid_tickers:
            prices_map[t] = prices_map[t][:min_len]
        bench_prices = bench_prices[:min_len]

        # equal-weight portfolio
        n = len(valid_tickers)
        weight = 1.0 / n

        equity = [float(capital)]
        bench_equity = [float(capital)]
        trades: list[TradeRecord] = []
        total_commission = 0.0
        total_slippage = 0.0

        # initial buy
        for t in valid_tickers:
            p = prices_map[t][0]["close"]
            shares = (capital * weight) / p
            comm = capital * weight * commission_pct
            slip = capital * weight * slippage_pct
            total_commission += comm
            total_slippage += slip
            trades.append(
                TradeRecord(
                    date=prices_map[t][0]["date"],
                    ticker=t,
                    action="BUY",
                    price=p,
                    shares=shares,
                    value=capital * weight,
                    commission=comm,
                    slippage=slip,
                )
            )

        portfolio_dates = [p["date"] for p in bench_prices]

        for i in range(1, min_len):
            port_val = 0.0
            for t in valid_tickers:
                p = prices_map[t]
                prev_close = p[i - 1]["close"]
                curr_close = p[i]["close"]
                ret = (curr_close - prev_close) / prev_close
                port_val += equity[i - 1] * weight * (1 + ret)
            bench_ret = (bench_prices[i]["close"] - bench_prices[i - 1]["close"]) / bench_prices[i - 1]["close"]
            comm = port_val * weight * commission_pct
            slip = port_val * weight * slippage_pct
            total_commission += comm
            total_slippage += slip
            tax = max(0, (port_val - equity[i - 1])) * tax_rate if port_val > equity[i - 1] else 0
            port_val -= comm + slip + tax
            equity.append(port_val)
            bench_equity.append(bench_equity[i - 1] * (1 + bench_ret))

        equity_curve = [
            {"date": portfolio_dates[i].isoformat(), "portfolio": equity[i], "benchmark": bench_equity[i]}
            for i in range(min_len)
        ]

        port_returns = _returns(equity)

        total_return = (equity[-1] / equity[0]) - 1
        bench_total_return = (bench_equity[-1] / bench_equity[0]) - 1

        # monthly returns
        monthly: dict[str, list[float]] = {}
        for i in range(1, min_len):
            m = portfolio_dates[i].strftime("%Y-%m")
            r = (equity[i] - equity[i - 1]) / equity[i - 1]
            monthly.setdefault(m, []).append(r)
        monthly_returns = [{"month": m, "return": np.mean(rs)} for m, rs in sorted(monthly.items())]

        # walk-forward: 2 folds
        wf_folds: list[WalkForwardFold] = []
        fold_size = min_len // 2
        for fold in range(2):
            ts = fold * fold_size
            te = ts + fold_size
            if te >= min_len - 20:
                break
            # train on first half, test on second half
            if fold == 0:
                test_slice = equity[te:]
            else:
                test_slice = equity[te:]

            wf_port_ret = (test_slice[-1] / test_slice[0]) - 1 if len(test_slice) > 1 else 0
            wf_bench_slice = bench_equity[te:] if fold == 0 else bench_equity[te:]
            wf_bench_ret = (wf_bench_slice[-1] / wf_bench_slice[0]) - 1 if len(wf_bench_slice) > 1 else 0
            wf_sharpe = _sharpe(_returns(test_slice)) if len(test_slice) > 5 else 0
            wf_mdd = _max_dd(test_slice) if len(test_slice) > 1 else 0

            wf_folds.append(
                WalkForwardFold(
                    fold=fold + 1,
                    train_start=portfolio_dates[ts],
                    train_end=portfolio_dates[min(te - 1, len(portfolio_dates) - 1)],
                    test_start=portfolio_dates[te] if te < len(portfolio_dates) else portfolio_dates[-1],
                    test_end=portfolio_dates[-1],
                    portfolio_return=wf_port_ret,
                    benchmark_return=wf_bench_ret,
                    sharpe=wf_sharpe,
                    max_drawdown=wf_mdd,
                    trades=len(valid_tickers),
                )
            )

        result = PersonalBacktestResult(
            tickers=valid_tickers,
            start_date=start,
            end_date=end,
            initial_capital=capital,
            final_capital=equity[-1],
            total_return=total_return,
            benchmark_return=bench_total_return,
            alpha=total_return - bench_total_return,
            sharpe=_sharpe(port_returns),
            sortino=_sortino(port_returns),
            calmar=_calmar(port_returns, equity),
            max_drawdown=_max_dd(equity),
            win_rate=float(np.mean(port_returns > 0)) if len(port_returns) > 0 else 0,
            profit_factor=float(sum(port_returns[port_returns > 0]) / abs(sum(port_returns[port_returns < 0])))
            if any(port_returns < 0)
            else float("inf"),
            total_commission=total_commission,
            total_slippage=total_slippage,
            n_trades=len(trades),
            equity_curve=equity_curve,
            monthly_returns=monthly_returns,
            trades=trades,
            walk_forward=wf_folds,
            benchmark_ticker=benchmark,
        )
        return result
    finally:
        db.close()
