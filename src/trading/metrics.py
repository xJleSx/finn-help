from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

ANNUAL_FACTOR = 252


@dataclass
class PerformanceMetrics:
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    omega: float = 0.0
    max_drawdown: float = 0.0
    avg_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    recovery_factor: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    volatility: float = 0.0
    downside_volatility: float = 0.0
    best_day: float = 0.0
    worst_day: float = 0.0
    avg_daily_return: float = 0.0
    monthly_returns: list[dict[str, Any]] = field(default_factory=list)
    rolling_sharpe: list[float] = field(default_factory=list)
    rolling_volatility: list[float] = field(default_factory=list)
    rolling_max_dd: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    drawdown_curve: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "omega": self.omega,
            "max_drawdown": self.max_drawdown,
            "avg_drawdown": self.avg_drawdown,
            "max_drawdown_duration": self.max_drawdown_duration,
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "profit_factor": self.profit_factor,
            "n_trades": self.n_trades,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "recovery_factor": self.recovery_factor,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "volatility": self.volatility,
            "downside_volatility": self.downside_volatility,
            "best_day": self.best_day,
            "worst_day": self.worst_day,
            "avg_daily_return": self.avg_daily_return,
            "monthly_returns": self.monthly_returns,
        }

    def summary(self) -> str:
        return (
            f"📊 *Performance Metrics*\n\n"
            f"📈 Total Return: {self.total_return:+.2%}\n"
            f"📈 Annual Return: {self.annual_return:+.2%}\n"
            f"⚙ Sharpe: {self.sharpe:.2f}\n"
            f"⚙ Sortino: {self.sortino:.2f}\n"
            f"⚙ Calmar: {self.calmar:.2f}\n"
            f"⚠ Max Drawdown: {self.max_drawdown:.2%}\n"
            f"🎯 Win Rate: {self.win_rate:.1%} ({self.n_wins}/{self.n_trades})\n"
            f"📈 Profit Factor: {self.profit_factor:.2f}\n"
            f"🔄 Consecutive Wins: {self.consecutive_wins} / Losses: {self.consecutive_losses}\n"
            f"🔴 VaR(95%): {self.var_95:.2%}\n"
            f"🔴 CVaR(95%): {self.cvar_95:.2%}\n"
            f"📊 Volatility: {self.volatility:.2%}\n"
        )


def compute_metrics(
    equity: list[float],
    trades: list[dict[str, Any]] | None = None,
    benchmark: list[float] | None = None,
    annual_factor: int = ANNUAL_FACTOR,
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    if len(equity) < 5:
        return PerformanceMetrics()

    eq_arr = np.array(equity, dtype=float)
    returns = np.diff(eq_arr) / eq_arr[:-1]

    if len(returns) < 2:
        return PerformanceMetrics(equity_curve=equity)

    total_return = (eq_arr[-1] / eq_arr[0]) - 1
    n_days = len(returns)
    annual_return = (1 + total_return) ** (annual_factor / n_days) - 1 if n_days > 0 else 0.0
    avg_daily_return = float(np.mean(returns))

    volatility = float(np.std(returns, ddof=1))
    annual_vol = volatility * np.sqrt(annual_factor)

    downside = returns[returns < 0]
    downside_vol = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    annual_downside_vol = downside_vol * np.sqrt(annual_factor)

    sharpe = ((annual_return - risk_free_rate) / annual_vol) if annual_vol > 1e-10 else 0.0
    sortino = ((annual_return - risk_free_rate) / annual_downside_vol) if annual_downside_vol > 1e-10 else 0.0

    cumulative = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cumulative)
    dd_arr = (cumulative - peak) / peak
    max_dd = float(np.min(dd_arr))
    avg_dd = float(np.mean(dd_arr[dd_arr < 0])) if np.any(dd_arr < 0) else 0.0

    in_drawdown = False
    current_duration = 0
    max_duration = 0
    for d in dd_arr:
        if d < 0:
            if not in_drawdown:
                in_drawdown = True
                current_duration = 1
            else:
                current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            in_drawdown = False
            current_duration = 0

    calmar = (annual_return / abs(max_dd)) if max_dd < 0 else 0.0

    avg_positive = float(np.mean(returns[returns > 0])) if np.any(returns > 0) else 0.0
    avg_negative = float(np.mean(returns[returns < 0])) if np.any(returns < 0) else 0.0

    total_gain = float(np.sum(returns[returns > 0]))
    total_loss = float(abs(np.sum(returns[returns < 0])))
    profit_factor = (total_gain / total_loss) if total_loss > 1e-10 else float("inf")

    n_wins = int(np.sum(returns > 0))
    n_losses = int(np.sum(returns < 0))
    win_rate = n_wins / len(returns) if len(returns) > 0 else 0.0

    rec_factor = total_return / abs(max_dd) if max_dd < 0 else 0.0

    sorted_returns = np.sort(returns)
    var_95 = float(np.percentile(sorted_returns, 5))
    cvar_95 = float(np.mean(sorted_returns[sorted_returns <= var_95])) if np.any(sorted_returns <= var_95) else var_95

    best_day = float(np.max(returns)) if len(returns) > 0 else 0.0
    worst_day = float(np.min(returns)) if len(returns) > 0 else 0.0

    # Consecutive wins/losses
    cons_w = 0
    cons_l = 0
    max_cons_w = 0
    max_cons_l = 0
    for r in returns:
        if r > 0:
            cons_w += 1
            cons_l = 0
            max_cons_w = max(max_cons_w, cons_w)
        elif r < 0:
            cons_l += 1
            cons_w = 0
            max_cons_l = max(max_cons_l, cons_l)
        else:
            cons_w = 0
            cons_l = 0

    # Rolling metrics (window = annual_factor)
    window = min(annual_factor, len(returns))
    roll_sharpe: list[float] = []
    roll_vol: list[float] = []
    roll_dd: list[float] = []
    for i in range(window, len(returns) + 1):
        rw = returns[i - window : i]
        rw_vol = float(np.std(rw, ddof=1)) * np.sqrt(annual_factor)
        rw_sharpe = (float(np.mean(rw)) * annual_factor / rw_vol) if rw_vol > 1e-10 else 0.0
        roll_sharpe.append(rw_sharpe)
        roll_vol.append(rw_vol)

        rw_cum = np.cumprod(1 + rw)
        rw_peak = np.maximum.accumulate(rw_cum)
        rw_dd = float(np.min((rw_cum - rw_peak) / rw_peak))
        roll_dd.append(rw_dd)

    # Monthly returns
    monthly: dict[str, list[float]] = {}
    if n_days > 0:
        trading_days_per_month = annual_factor / 12
        n_months = max(1, int(n_days / trading_days_per_month))
        for m in range(n_months):
            start = int(m * trading_days_per_month)
            end = min(int((m + 1) * trading_days_per_month), len(returns))
            if end > start:
                m_ret = float(np.prod(1 + returns[start:end]) - 1)
                monthly[str(m + 1)] = [m_ret]

    omega_num = float(np.sum(returns[returns > 0] - risk_free_rate / annual_factor))
    omega_den = float(abs(np.sum(returns[returns < 0] - risk_free_rate / annual_factor)))
    omega = omega_num / omega_den if omega_den > 1e-10 else float("inf")

    n_trades = len(trades) if trades else n_wins + n_losses

    return PerformanceMetrics(
        total_return=total_return,
        annual_return=annual_return,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        omega=omega,
        max_drawdown=max_dd,
        avg_drawdown=avg_dd,
        max_drawdown_duration=max_duration,
        win_rate=win_rate,
        avg_win=avg_positive,
        avg_loss=avg_negative,
        profit_factor=profit_factor,
        n_trades=n_trades,
        n_wins=n_wins,
        n_losses=n_losses,
        consecutive_wins=max_cons_w,
        consecutive_losses=max_cons_l,
        recovery_factor=rec_factor,
        var_95=var_95,
        cvar_95=cvar_95,
        volatility=annual_vol,
        downside_volatility=annual_downside_vol,
        best_day=best_day,
        worst_day=worst_day,
        avg_daily_return=avg_daily_return,
        monthly_returns=[{"month": k, "return": float(np.mean(v))} for k, v in sorted(monthly.items())],
        rolling_sharpe=roll_sharpe,
        rolling_volatility=roll_vol,
        rolling_max_dd=roll_dd,
        equity_curve=equity,
        drawdown_curve=dd_arr.tolist(),
    )
