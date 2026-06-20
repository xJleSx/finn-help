import logging
from datetime import date, timedelta

import numpy as np

from src.analysis.personal_backtest import run_personal_backtest
from src.config import personal

logger = logging.getLogger(__name__)


def generate_weekly_report() -> bytes | None:
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        bt = personal.get("backtest", {})
        end = date.today()
        start = end - timedelta(days=120)

        result = run_personal_backtest(
            start=start,
            end=end,
            capital=100_000,
        )

        # build figure
        fig, axes = plt.subplots(3, 1, figsize=(10, 10), gridspec_kw={"height_ratios": [3, 1.2, 1.2]})
        fig.suptitle(
            f"Weekly Report: {start.isoformat()} to {end.isoformat()}",
            fontsize=14, fontweight="bold",
        )

        # 1. Equity curve
        ax1 = axes[0]
        ec = result.equity_curve
        if ec:
            dates_p = [r["date"] for r in ec]
            port = [r["portfolio"] for r in ec]
            bench = [r["benchmark"] for r in ec]
            ax1.plot(dates_p, port, label=f"Portfolio ({result.total_return:+.1%})", linewidth=2)
            ax1.plot(dates_p, bench, label=f"IMOEX ({result.benchmark_return:+.1%})", linewidth=1, alpha=0.6)
            ax1.legend()
            ax1.set_ylabel("Capital, RUB")
            ax1.grid(True, alpha=0.3)
            ticks = dates_p[::max(1, len(dates_p) // 6)]
            ax1.set_xticks(ticks)
            ax1.tick_params(axis="x", rotation=30)

        # 2. Monthly returns bar
        ax2 = axes[1]
        mr = result.monthly_returns
        if mr:
            labels = [r["month"] for r in mr]
            vals = [r["return"] for r in mr]
            colors = ["#22c55e" if v >= 0 else "#ef4444" for v in vals]
            ax2.bar(labels, vals, color=colors, width=0.6)
            ax2.axhline(y=0, color="gray", linewidth=0.5)
            ax2.set_ylabel("Return")
            ax2.set_title("Monthly Returns")
            ax2.set_xticks(range(len(labels)))
            ax2.set_xticklabels(labels, rotation=30, fontsize=8)
            ax2.grid(True, alpha=0.3, axis="y")

        # 3. Drawdown
        ax3 = axes[2]
        if ec:
            eq_arr = np.array([r["portfolio"] for r in ec])
            peak = np.maximum.accumulate(eq_arr)
            dd = (eq_arr - peak) / peak
            ax3.fill_between(range(len(dd)), dd, 0, color="#ef4444", alpha=0.4, label=f"Max DD: {result.max_drawdown:.1%}")
            ax3.plot(dd, color="#dc2626", linewidth=1)
            ax3.set_ylabel("Drawdown")
            ax3.set_title("Drawdown")
            ax3.grid(True, alpha=0.3)
            ax3.legend()

        # stats box
        stats_text = (
            f"Return: {result.total_return:+.1%}  |  Alpha: {result.alpha:+.1%}  |  "
            f"Sharpe: {result.sharpe:.2f}  |  Sortino: {result.sortino:.2f}  |  "
            f"Max DD: {result.max_drawdown:.1%}  |  Win Rate: {result.win_rate:.1%}"
        )
        fig.text(0.5, 0.01, stats_text, ha="center", fontsize=9, style="italic", alpha=0.7)

        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning("Weekly report generation failed: %s", e, exc_info=True)
        return None
